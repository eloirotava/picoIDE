use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Query,
    },
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
};

#[derive(Serialize)]
struct FileNode { name: String, path: String, is_dir: bool }

#[derive(Deserialize)]
struct FileQuery { path: Option<String> }

#[derive(Deserialize)]
struct ReadQuery { path: String }

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
async fn ws_handler(ws: WebSocketUpgrade) -> axum::response::Response {
    ws.on_upgrade(handle_terminal)
}

async fn handle_terminal(socket: WebSocket) {
    let pty_system = NativePtySystem::default();
    let pair = pty_system.openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 }).unwrap();
    
    let cmd = CommandBuilder::new("sh");
    let mut child = pair.slave.spawn_command(cmd).unwrap();
    let mut pty_reader = pair.master.try_clone_reader().unwrap();
    let mut pty_writer = pair.master.take_writer().unwrap();
    let master = pair.master;

    let (mut ws_sender, mut ws_receiver) = socket.split();

    let (tx, mut rx) = tokio::sync::mpsc::channel::<Vec<u8>>(32);
    std::thread::spawn(move || {
        let mut buf = [0u8; 1024];
        while let Ok(n) = pty_reader.read(&mut buf) {
            if n == 0 { break; }
            if tx.blocking_send(buf[..n].to_vec()).is_err() { break; }
        }
    });

    let mut send_task = tokio::spawn(async move {
        while let Some(data) = rx.recv().await {
            if ws_sender.send(Message::Binary(data)).await.is_err() { break; }
        }
    });

    let mut recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = ws_receiver.next().await {
            if let Message::Text(text) = msg {
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
        }
    });

    tokio::select! {
        _ = (&mut send_task) => recv_task.abort(),
        _ = (&mut recv_task) => send_task.abort(),
    };
    let _ = child.kill();
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

async fn read_file(Query(query): Query<ReadQuery>) -> String {
    fs::read_to_string(&query.path).unwrap_or_else(|_| "Erro ao ler arquivo.".to_string())
}

async fn save_file(Json(payload): Json<SaveRequest>) -> String {
    match fs::write(&payload.path, &payload.content) {
        Ok(_) => "Salvo com sucesso!".to_string(),
        Err(e) => format!("Erro ao salvar: {}", e),
    }
}