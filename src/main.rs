use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Query,
    },
    http::StatusCode,
    response::Html,
    routing::{get, post},
    Json, Router,
};
use futures_util::{sink::SinkExt, stream::StreamExt};
use portable_pty::{CommandBuilder, NativePtySystem, PtySize, PtySystem};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::{Read, Write},
    net::SocketAddr,
    path::Path,
    time::Duration,
};

// Proxies reversos (nginx, Cloudflare, etc) matam a conexão quando o SERVIDOR
// fica um tempo sem mandar nada. Um Ping periódico mantém o túnel vivo.
const INTERVALO_KEEPALIVE: Duration = Duration::from_secs(20);

#[derive(Serialize)]
struct FileNode { name: String, path: String, is_dir: bool }

#[derive(Deserialize)]
struct FileQuery { path: Option<String> }

#[derive(Deserialize)]
struct ReadQuery { path: String }

// Pasta onde o shell deve nascer, para o terminal não voltar pra raiz a cada recarregada.
#[derive(Deserialize)]
struct TerminalQuery { cwd: Option<String> }

#[derive(Deserialize)]
struct SaveRequest { path: String, content: String }

#[derive(Deserialize)]
#[serde(tag = "type")]
enum WsTerminalMessage {
    #[serde(rename = "input")] Input { data: String },
    #[serde(rename = "resize")] Resize { cols: u16, rows: u16 },
    #[serde(rename = "ping")] Ping,
}

#[tokio::main]
async fn main() {
    let app = Router::new()
        // Servindo o HTML direto da memória RAM!
        .route("/", get(serve_index))
        .route("/api/files", get(list_files))
        .route("/api/read", get(read_file))
        .route("/api/save", post(save_file))
        .route("/api/ws", get(ws_handler));

    let porta = 8080;
    let addr = SocketAddr::from(([0, 0, 0, 0], porta));

    println!("🚀 Pico IDE (Binário Único) rodando na porta {}!", porta);

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

// A MÁGICA ACONTECE AQUI: 
// O include_str! injeta o conteúdo do index.html dentro do executável no momento da compilação.
async fn serve_index() -> Html<&'static str> {
    Html(include_str!("../static/index.html"))
}

// --- TERMINAL ---
async fn ws_handler(ws: WebSocketUpgrade, Query(query): Query<TerminalQuery>) -> axum::response::Response {
    ws.on_upgrade(move |socket| handle_terminal(socket, query.cwd))
}

// Usa o shell de login do usuário quando ele existir; cai pro "sh" se não.
fn shell_do_sistema() -> String {
    match std::env::var("SHELL") {
        Ok(shell) if Path::new(&shell).is_file() => shell,
        _ => "sh".to_string(),
    }
}

async fn handle_terminal(socket: WebSocket, cwd: Option<String>) {
    let pty_system = NativePtySystem::default();
    let pair = pty_system.openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 }).unwrap();

    let mut cmd = CommandBuilder::new(shell_do_sistema());
    // Sem TERM o xterm.js não recebe as sequências de cor/cursor corretas.
    cmd.env("TERM", "xterm-256color");
    // Só aceita a pasta se ela realmente existir, senão o spawn falharia.
    if let Some(dir) = cwd.filter(|d| Path::new(d).is_dir()) {
        cmd.cwd(dir);
    }

    let mut child = pair.slave.spawn_command(cmd).unwrap();
    // Precisa soltar o slave aqui: enquanto o processo pai segurar essa ponta do
    // PTY, o read() no master nunca retorna quando o shell morre, e a conexão
    // ficaria pendurada para sempre.
    drop(pair.slave);

    let mut pty_reader = pair.master.try_clone_reader().unwrap();
    let mut pty_writer = pair.master.take_writer().unwrap();
    let master = pair.master;

    let (mut ws_sender, mut ws_receiver) = socket.split();

    // O canal carrega Message em vez de bytes crus, para o keepalive poder
    // compartilhar o mesmo sender do PTY sem brigar por ele.
    let (tx, mut rx) = tokio::sync::mpsc::channel::<Message>(32);

    let tx_pty = tx.clone();
    std::thread::spawn(move || {
        let mut buf = [0u8; 4096];
        loop {
            match pty_reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if tx_pty.blocking_send(Message::Binary(buf[..n].to_vec())).is_err() { return; }
                }
            }
        }
        // Shell terminou (exit/Ctrl+D): avisa o navegador para ele não ficar
        // reconectando achando que foi queda de rede.
        let _ = tx_pty.blocking_send(Message::Close(None));
    });

    let keepalive_task = tokio::spawn(async move {
        let mut ticker = tokio::time::interval(INTERVALO_KEEPALIVE);
        ticker.tick().await; // o primeiro tick dispara na hora, descartamos
        loop {
            ticker.tick().await;
            if tx.send(Message::Ping(Vec::new())).await.is_err() { break; }
        }
    });

    let mut send_task = tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            let era_close = matches!(msg, Message::Close(_));
            if ws_sender.send(msg).await.is_err() { break; }
            if era_close { break; }
        }
    });

    let mut recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = ws_receiver.next().await {
            match msg {
                Message::Text(text) => {
                    if let Ok(ws_msg) = serde_json::from_str::<WsTerminalMessage>(&text) {
                        match ws_msg {
                            WsTerminalMessage::Input { data } => {
                                let _ = pty_writer.write_all(data.as_bytes());
                                let _ = pty_writer.flush();
                            }
                            WsTerminalMessage::Resize { cols, rows } => {
                                let _ = master.resize(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 });
                            }
                            WsTerminalMessage::Ping => {}
                        }
                    }
                }
                Message::Close(_) => break,
                // Ping/Pong são respondidos pela própria camada do axum.
                _ => {}
            }
        }
    });

    tokio::select! {
        _ = (&mut send_task) => recv_task.abort(),
        _ = (&mut recv_task) => send_task.abort(),
    };
    keepalive_task.abort();
    let _ = child.kill();
    let _ = child.wait();
}

// --- ARQUIVOS ---
async fn list_files(Query(query): Query<FileQuery>) -> Json<Vec<FileNode>> {
    let mut files = Vec::new();
    let target_path = query.path.unwrap_or_else(|| "/".to_string());

    if let Ok(entries) = fs::read_dir(&target_path) {
        for entry in entries.flatten() {
            let path = entry.path();
            files.push(FileNode {
                name: entry.file_name().to_string_lossy().into_owned(),
                path: path.to_string_lossy().into_owned(),
                is_dir: path.is_dir(),
            });
        }
    }
    files.sort_by(|a, b| b.is_dir.cmp(&a.is_dir).then(a.name.cmp(&b.name)));
    Json(files)
}

// Devolve 404 quando o arquivo não existe mais, para o navegador conseguir
// distinguir "arquivo apagado" de "arquivo com o texto 'Erro ao ler arquivo.'"
// ao restaurar a última sessão.
async fn read_file(Query(query): Query<ReadQuery>) -> Result<String, StatusCode> {
    fs::read_to_string(&query.path).map_err(|_| StatusCode::NOT_FOUND)
}

async fn save_file(Json(payload): Json<SaveRequest>) -> String {
    match fs::write(&payload.path, &payload.content) {
        Ok(_) => "Salvo com sucesso!".to_string(),
        Err(e) => format!("Erro ao salvar: {}", e),
    }
}