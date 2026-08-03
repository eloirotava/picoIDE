use axum::{
    body::Body,
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        DefaultBodyLimit, Path as ParamCaminho, Query, State,
    },
    http::{header, StatusCode},
    response::{Html, IntoResponse},
    routing::{get, post},
    Json, Router,
};
use futures_util::{sink::SinkExt, stream::StreamExt};
use portable_pty::{Child, CommandBuilder, MasterPty, NativePtySystem, PtySize, PtySystem};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    io::{Read, Write},
    net::SocketAddr,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tokio::{
    io::AsyncWriteExt,
    sync::{broadcast, mpsc},
};
use tokio_util::io::ReaderStream;

// Proxies reversos (nginx, Cloudflare, etc) matam a conexão quando o SERVIDOR
// fica um tempo sem mandar nada. Um Ping periódico mantém o túnel vivo.
const INTERVALO_KEEPALIVE: Duration = Duration::from_secs(20);

// Quanto da saída fica guardado para quem reata ver o que passou enquanto a
// aba esteve fechada. 256 KB cobre bem a cauda de um build sem inchar a RAM
// da placa.
const SCROLLBACK_MAX: usize = 256 * 1024;

// Teto de shells simultâneos. Sem isso, cada navegador que perde o id deixaria
// um shell para trás e a placa acabaria sem memória.
const MAX_SESSOES: usize = 16;

// Uma sessão de terminal: vive no servidor, independente de qualquer websocket.
struct Sessao {
    entrada: mpsc::UnboundedSender<Vec<u8>>,
    master: Mutex<Box<dyn MasterPty + Send>>,
    processo: Mutex<Box<dyn Child + Send + Sync>>,
    saida: broadcast::Sender<Vec<u8>>,
    scrollback: Mutex<Vec<u8>>,
    viva: AtomicBool,
    clientes: AtomicUsize,
    criada: Instant,
}

impl Sessao {
    fn encerrar(&self) {
        self.viva.store(false, Ordering::SeqCst);
        if let Ok(mut processo) = self.processo.lock() {
            let _ = processo.kill();
            let _ = processo.wait();
        }
    }
}

type Registro = Arc<Mutex<HashMap<String, Arc<Sessao>>>>;

#[derive(Serialize)]
struct FileNode { name: String, path: String, is_dir: bool }

#[derive(Deserialize)]
struct FileQuery { path: Option<String> }

#[derive(Deserialize)]
struct ReadQuery { path: String }

// "cwd" é a pasta onde um shell NOVO nasce. "sessao" é o id de uma sessão já
// existente para reatar — quando ele vem, o cwd é ignorado, porque o shell
// mantém a pasta em que ele já está.
#[derive(Deserialize)]
struct TerminalQuery { cwd: Option<String>, sessao: Option<String> }

#[derive(Deserialize)]
struct SaveRequest { path: String, content: String }

#[derive(Deserialize)]
#[serde(tag = "type")]
enum WsTerminalMessage {
    #[serde(rename = "input")] Input { data: String },
    #[serde(rename = "resize")] Resize { cols: u16, rows: u16 },
    #[serde(rename = "ping")] Ping,
}

const PORTA_PADRAO: u16 = 8080;

// Argumentos na mão em vez de uma crate de CLI: é uma opção só, e o binário
// vai para uma placa onde cada dependência pesa no tamanho e no tempo de build.
fn porta_dos_argumentos() -> u16 {
    let mut args = std::env::args().skip(1);

    while let Some(arg) = args.next() {
        let valor = match arg.as_str() {
            "-h" | "--ajuda" | "--help" => {
                println!("picoIDE — IDE mínima servida por um executável só.\n");
                println!("Uso: picoide [--porta N]\n");
                println!("  -p, --porta N   Porta onde escutar (padrão: {}).", PORTA_PADRAO);
                println!("  -h, --ajuda     Mostra esta ajuda.");
                std::process::exit(0);
            }
            "-p" | "--porta" => args.next(),
            outro if outro.starts_with("--porta=") => {
                Some(outro["--porta=".len()..].to_string())
            }
            // Um número solto também vale: "picoide 9090".
            outro if outro.parse::<u16>().is_ok() => Some(outro.to_string()),
            outro => {
                eprintln!("Argumento desconhecido: {}. Use --ajuda.", outro);
                std::process::exit(2);
            }
        };

        // Porta inválida é erro duro: escutar numa porta diferente da pedida
        // faria o usuário procurar o problema no lugar errado.
        match valor.as_deref().map(str::parse::<u16>) {
            Some(Ok(0)) | None => {
                eprintln!("--porta precisa de um número entre 1 e 65535.");
                std::process::exit(2);
            }
            Some(Err(_)) => {
                eprintln!("Porta inválida: {}. Use um número entre 1 e 65535.",
                          valor.unwrap_or_default());
                std::process::exit(2);
            }
            Some(Ok(n)) => return n,
        }
    }

    PORTA_PADRAO
}

#[tokio::main]
async fn main() {
    let registro: Registro = Arc::new(Mutex::new(HashMap::new()));

    let app = Router::new()
        // Servindo o HTML direto da memória RAM!
        .route("/", get(serve_index))
        .route("/vendor/*caminho", get(serve_vendor))
        .route("/icone.svg", get(serve_icone))
        .route("/api/files", get(list_files))
        .route("/api/read", get(read_file))
        .route("/api/save", post(save_file))
        .route("/api/download", get(download_file))
        // O limite padrão do axum (2 MB) barraria justamente o caso de uso:
        // subir um binário para a placa. O corpo vai direto para o disco em
        // pedaços, então não é a RAM que dita o teto.
        .route("/api/upload", post(upload_file).layer(DefaultBodyLimit::disable()))
        .route("/api/ws", get(ws_handler))
        .route("/api/terminal/encerrar", post(encerrar_sessao))
        .with_state(registro);

    let porta = porta_dos_argumentos();
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

// SVG em vez de .ico: um arquivo de texto de 500 bytes que fica nítido em
// qualquer tamanho, e que vai embutido como o resto.
async fn serve_icone() -> impl IntoResponse {
    (
        [
            (header::CONTENT_TYPE, "image/svg+xml"),
            (header::CACHE_CONTROL, CACHE_ASSETS),
        ],
        include_str!("../static/icone.svg"),
    )
}

// --- LIBS DA INTERFACE ---
// CodeMirror e xterm.js também vão embutidos, e não buscados em CDN: a placa
// pode não ter internet, e nesse caso o editor e o terminal simplesmente não
// carregariam. Para trocar de versão, veja static/vendor/atualizar.sh.
const JS: &str = "application/javascript; charset=utf-8";
const CSS: &str = "text/css; charset=utf-8";

// Uma hora é curto o bastante para uma troca de versão aparecer sozinha (os
// caminhos não têm hash), e longo o bastante para o F5 não rebaixar ~900 KB.
const CACHE_ASSETS: &str = "public, max-age=3600";

const ASSETS: &[(&str, &str, &[u8])] = &[
    ("codemirror/lib/codemirror.js", JS, include_bytes!("../static/vendor/codemirror/lib/codemirror.js")),
    ("codemirror/lib/codemirror.css", CSS, include_bytes!("../static/vendor/codemirror/lib/codemirror.css")),
    ("codemirror/theme/dracula.css", CSS, include_bytes!("../static/vendor/codemirror/theme/dracula.css")),
    ("codemirror/addon/mode/simple.js", JS, include_bytes!("../static/vendor/codemirror/addon/mode/simple.js")),
    ("codemirror/mode/javascript/javascript.js", JS, include_bytes!("../static/vendor/codemirror/mode/javascript/javascript.js")),
    ("codemirror/mode/rust/rust.js", JS, include_bytes!("../static/vendor/codemirror/mode/rust/rust.js")),
    ("codemirror/mode/xml/xml.js", JS, include_bytes!("../static/vendor/codemirror/mode/xml/xml.js")),
    ("codemirror/mode/css/css.js", JS, include_bytes!("../static/vendor/codemirror/mode/css/css.js")),
    ("codemirror/mode/htmlmixed/htmlmixed.js", JS, include_bytes!("../static/vendor/codemirror/mode/htmlmixed/htmlmixed.js")),
    ("codemirror/mode/toml/toml.js", JS, include_bytes!("../static/vendor/codemirror/mode/toml/toml.js")),
    ("xterm/lib/xterm.js", JS, include_bytes!("../static/vendor/xterm/lib/xterm.js")),
    ("xterm/css/xterm.css", CSS, include_bytes!("../static/vendor/xterm/css/xterm.css")),
    ("xterm-addon-fit/lib/xterm-addon-fit.js", JS, include_bytes!("../static/vendor/xterm-addon-fit/lib/xterm-addon-fit.js")),
];

async fn serve_vendor(ParamCaminho(caminho): ParamCaminho<String>) -> Result<impl IntoResponse, StatusCode> {
    let (_, tipo, corpo) = ASSETS
        .iter()
        .find(|(nome, _, _)| *nome == caminho)
        .ok_or(StatusCode::NOT_FOUND)?;

    Ok((
        [(header::CONTENT_TYPE, *tipo), (header::CACHE_CONTROL, CACHE_ASSETS)],
        *corpo,
    ))
}

// --- TERMINAL ---
// As sessões vivem no servidor, não no websocket: fechar a aba não pode matar
// uma compilação em andamento. O navegador guarda o id e reata na volta,
// recebendo de saída o que passou enquanto esteve fora.
async fn ws_handler(
    ws: WebSocketUpgrade,
    Query(query): Query<TerminalQuery>,
    State(registro): State<Registro>,
) -> axum::response::Response {
    ws.on_upgrade(move |socket| handle_terminal(socket, query, registro))
}

// Fechar a aba do terminal encerra a sessão de vez. Sem isso, cada terminal
// fechado deixaria um shell rodando até o teto de sessões reciclá-lo, e a
// pessoa não teria como matar um processo que ela mesma iniciou.
#[derive(Deserialize)]
struct SessaoQuery { sessao: String }

async fn encerrar_sessao(
    Query(query): Query<SessaoQuery>,
    State(registro): State<Registro>,
) -> StatusCode {
    let sessao = registro.lock().unwrap().remove(&query.sessao);
    match sessao {
        Some(s) => {
            s.encerrar();
            StatusCode::OK
        }
        None => StatusCode::NOT_FOUND,
    }
}

// Usa o shell de login do usuário quando ele existir; cai pro "sh" se não.
fn shell_do_sistema() -> String {
    match std::env::var("SHELL") {
        Ok(shell) if Path::new(&shell).is_file() => shell,
        _ => "sh".to_string(),
    }
}

fn novo_id() -> String {
    static SEQ: AtomicUsize = AtomicUsize::new(0);
    let n = SEQ.fetch_add(1, Ordering::SeqCst);
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{:x}{:x}", t, n)
}

// Mata as sessões órfãs mais antigas quando o teto é atingido. Sem isso, cada
// navegador novo (ou aba anônima) deixaria um shell para trás para sempre.
// Só entra em quem não tem ninguém conectado: uma sessão sendo usada, ou com
// build rodando e a aba fechada, não pode ser reciclada por baixo do usuário.
fn garantir_espaco(mapa: &mut HashMap<String, Arc<Sessao>>) {
    while mapa.len() >= MAX_SESSOES {
        let alvo = mapa
            .iter()
            .filter(|(_, s)| s.clientes.load(Ordering::SeqCst) == 0)
            .min_by_key(|(_, s)| s.criada)
            .map(|(id, _)| id.clone());

        match alvo {
            Some(id) => {
                if let Some(s) = mapa.remove(&id) {
                    s.encerrar();
                }
            }
            // Todas ocupadas: melhor deixar passar do teto do que derrubar
            // sessão de alguém.
            None => break,
        }
    }
}

fn criar_sessao(registro: &Registro, cwd: Option<String>) -> Result<(String, Arc<Sessao>), String> {
    let sistema = NativePtySystem::default();
    let par = sistema
        .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
        .map_err(|e| e.to_string())?;

    let mut cmd = CommandBuilder::new(shell_do_sistema());
    // Sem TERM o xterm.js não recebe as sequências de cor/cursor corretas.
    cmd.env("TERM", "xterm-256color");
    // Só aceita a pasta se ela realmente existir, senão o spawn falharia.
    if let Some(dir) = cwd.filter(|d| Path::new(d).is_dir()) {
        cmd.cwd(dir);
    }

    let processo = par.slave.spawn_command(cmd).map_err(|e| e.to_string())?;
    // Precisa soltar o slave aqui: enquanto o processo pai segurar essa ponta
    // do PTY, o read() no master nunca retorna quando o shell morre, e a
    // sessão ficaria pendurada para sempre.
    drop(par.slave);

    let mut leitor = par.master.try_clone_reader().map_err(|e| e.to_string())?;
    let mut escritor = par.master.take_writer().map_err(|e| e.to_string())?;

    let (tx_entrada, mut rx_entrada) = mpsc::unbounded_channel::<Vec<u8>>();
    let (tx_saida, _) = broadcast::channel::<Vec<u8>>(1024);

    let sessao = Arc::new(Sessao {
        entrada: tx_entrada,
        master: Mutex::new(par.master),
        processo: Mutex::new(processo),
        saida: tx_saida,
        scrollback: Mutex::new(Vec::new()),
        viva: AtomicBool::new(true),
        clientes: AtomicUsize::new(0),
        criada: Instant::now(),
    });

    let id = novo_id();

    // O teclado chega por canal em vez de escrever direto no PTY, para nenhum
    // cliente segurar o lock da sessão enquanto o write bloqueia.
    std::thread::spawn(move || {
        while let Some(dados) = rx_entrada.blocking_recv() {
            if escritor.write_all(&dados).is_err() {
                break;
            }
            let _ = escritor.flush();
        }
    });

    // Esta thread é a dona da sessão: roda enquanto o shell viver, tenha ou
    // não alguém conectado. É o que faz a compilação sobreviver ao F5.
    let s = sessao.clone();
    let reg = registro.clone();
    let id_thread = id.clone();
    std::thread::spawn(move || {
        let mut buf = [0u8; 4096];
        loop {
            match leitor.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let pedaco = buf[..n].to_vec();
                    // Guardar e transmitir sob o mesmo lock evita que quem
                    // está reatando perca um pedaço, ou o receba duas vezes,
                    // por ele ter chegado entre a cópia e a inscrição.
                    let mut historico = s.scrollback.lock().unwrap();
                    historico.extend_from_slice(&pedaco);
                    if historico.len() > SCROLLBACK_MAX {
                        let sobra = historico.len() - SCROLLBACK_MAX;
                        historico.drain(..sobra);
                    }
                    let _ = s.saida.send(pedaco);
                }
            }
        }

        // Shell terminou (exit/Ctrl+D): a sessão morre de vez.
        s.viva.store(false, Ordering::SeqCst);
        let _ = s.saida.send(Vec::new()); // sentinela de fim para quem estiver ouvindo
        reg.lock().unwrap().remove(&id_thread);
        s.encerrar();
    });

    Ok((id, sessao))
}

// Reata na sessão pedida quando ela ainda existe; senão abre uma nova. Um id
// desconhecido (servidor reiniciado, sessão encerrada) não é erro: cai no
// caminho de criar, que é o que o usuário espera ao voltar na página.
fn resolver_sessao(
    registro: &Registro,
    query: TerminalQuery,
) -> Result<(String, Arc<Sessao>, bool), String> {
    if let Some(id) = query.sessao.as_deref() {
        let existente = registro.lock().unwrap().get(id).cloned();
        if let Some(s) = existente {
            if s.viva.load(Ordering::SeqCst) {
                return Ok((id.to_string(), s, true));
            }
        }
    }

    let (id, sessao) = criar_sessao(registro, query.cwd)?;
    let mut mapa = registro.lock().unwrap();
    garantir_espaco(&mut mapa);
    mapa.insert(id.clone(), sessao.clone());
    Ok((id, sessao, false))
}

async fn handle_terminal(socket: WebSocket, query: TerminalQuery, registro: Registro) {
    let (mut ws_sender, mut ws_receiver) = socket.split();

    let (id, sessao, reatou) = match resolver_sessao(&registro, query) {
        Ok(v) => v,
        Err(erro) => {
            let aviso = format!("\r\n[Pico IDE] Não consegui abrir o shell: {}\r\n", erro);
            let _ = ws_sender.send(Message::Text(aviso)).await;
            let _ = ws_sender.send(Message::Close(None)).await;
            return;
        }
    };

    sessao.clientes.fetch_add(1, Ordering::SeqCst);

    // O navegador guarda este id para reatar na próxima visita.
    let anuncio = serde_json::json!({ "type": "sessao", "id": id, "reatou": reatou }).to_string();
    if ws_sender.send(Message::Text(anuncio)).await.is_err() {
        sessao.clientes.fetch_sub(1, Ordering::SeqCst);
        return;
    }

    // Cópia do histórico e inscrição sob o mesmo lock (ver a thread leitora).
    let (historico, mut rx_saida) = {
        let guarda = sessao.scrollback.lock().unwrap();
        (guarda.clone(), sessao.saida.subscribe())
    };

    if !historico.is_empty() && ws_sender.send(Message::Binary(historico)).await.is_err() {
        sessao.clientes.fetch_sub(1, Ordering::SeqCst);
        return;
    }

    // O canal carrega Message em vez de bytes crus, para o keepalive poder
    // compartilhar o mesmo sender da saída do PTY sem brigar por ele.
    let (tx, mut rx) = mpsc::channel::<Message>(64);

    let tx_saida = tx.clone();
    let bomba = tokio::spawn(async move {
        loop {
            match rx_saida.recv().await {
                // Vetor vazio é a sentinela de shell encerrado.
                Ok(dados) if dados.is_empty() => {
                    let _ = tx_saida.send(Message::Close(None)).await;
                    break;
                }
                Ok(dados) => {
                    if tx_saida.send(Message::Binary(dados)).await.is_err() {
                        break;
                    }
                }
                // Cliente lento: perde o atrasado e segue no vivo.
                Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(_) => break,
            }
        }
    });

    let keepalive_task = tokio::spawn(async move {
        let mut ticker = tokio::time::interval(INTERVALO_KEEPALIVE);
        ticker.tick().await; // o primeiro tick dispara na hora, descartamos
        loop {
            ticker.tick().await;
            if tx.send(Message::Ping(Vec::new())).await.is_err() {
                break;
            }
        }
    });

    let mut send_task = tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            let era_close = matches!(msg, Message::Close(_));
            if ws_sender.send(msg).await.is_err() {
                break;
            }
            if era_close {
                break;
            }
        }
    });

    let sessao_rx = sessao.clone();
    let mut recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = ws_receiver.next().await {
            match msg {
                Message::Text(text) => {
                    if let Ok(ws_msg) = serde_json::from_str::<WsTerminalMessage>(&text) {
                        match ws_msg {
                            WsTerminalMessage::Input { data } => {
                                if sessao_rx.entrada.send(data.into_bytes()).is_err() {
                                    break;
                                }
                            }
                            WsTerminalMessage::Resize { cols, rows } => {
                                if let Ok(master) = sessao_rx.master.lock() {
                                    let _ = master.resize(PtySize {
                                        rows,
                                        cols,
                                        pixel_width: 0,
                                        pixel_height: 0,
                                    });
                                }
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
    bomba.abort();

    // Repare no que NÃO acontece aqui: o shell continua vivo. Só largamos a
    // ponta do websocket; quem estava compilando segue compilando.
    sessao.clientes.fetch_sub(1, Ordering::SeqCst);
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
// 415 (e não 404) quando o arquivo existe mas não é texto: o editor não tem o
// que mostrar, mas o arquivo é real e precisa continuar sendo o "arquivo
// aberto" para poder ser baixado.
async fn read_file(Query(query): Query<ReadQuery>) -> Result<String, StatusCode> {
    let dados = fs::read(&query.path).map_err(|_| StatusCode::NOT_FOUND)?;
    String::from_utf8(dados).map_err(|_| StatusCode::UNSUPPORTED_MEDIA_TYPE)
}

// --- UPLOAD E DOWNLOAD ---
// Os dois passam em fluxo, sem juntar o arquivo inteiro na memória: a placa
// tem pouca RAM e o caso de uso é justamente mover binário de build.

// Nome de arquivo em cabeçalho HTTP não aceita acento cru, e "relatório.pdf"
// é o caso comum aqui. Mandamos as duas formas: o ASCII para clientes velhos
// e o filename* (RFC 5987) para os que entendem UTF-8.
fn escapar_nome(nome: &str) -> String {
    let mut saida = String::new();
    for byte in nome.as_bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                saida.push(*byte as char)
            }
            _ => saida.push_str(&format!("%{:02X}", byte)),
        }
    }
    saida
}

async fn download_file(Query(query): Query<ReadQuery>) -> Result<impl IntoResponse, StatusCode> {
    let caminho = std::path::PathBuf::from(&query.path);
    // Uma pasta aqui viraria um erro de leitura confuso mais adiante.
    if caminho.is_dir() {
        return Err(StatusCode::BAD_REQUEST);
    }

    let arquivo = tokio::fs::File::open(&caminho)
        .await
        .map_err(|_| StatusCode::NOT_FOUND)?;

    let nome = caminho
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("arquivo");
    let simples: String = nome
        .chars()
        .map(|c| if c.is_ascii_graphic() && c != '"' { c } else { '_' })
        .collect();
    let disposicao = format!(
        "attachment; filename=\"{}\"; filename*=UTF-8''{}",
        simples,
        escapar_nome(nome)
    );

    Ok((
        [
            (header::CONTENT_TYPE, "application/octet-stream".to_string()),
            (header::CONTENT_DISPOSITION, disposicao),
        ],
        Body::from_stream(ReaderStream::new(arquivo)),
    ))
}

async fn upload_file(
    Query(query): Query<ReadQuery>,
    corpo: Body,
) -> Result<String, (StatusCode, String)> {
    let caminho = std::path::PathBuf::from(&query.path);
    if caminho.is_dir() {
        return Err((
            StatusCode::BAD_REQUEST,
            "Já existe uma pasta com esse nome.".to_string(),
        ));
    }

    let mut arquivo = tokio::fs::File::create(&caminho)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let mut fluxo = corpo.into_data_stream();
    let mut total: u64 = 0;
    while let Some(pedaco) = fluxo.next().await {
        let pedaco = pedaco.map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
        arquivo
            .write_all(&pedaco)
            .await
            .map_err(|e| (StatusCode::INSUFFICIENT_STORAGE, e.to_string()))?;
        total += pedaco.len() as u64;
    }
    // Sem o flush, um erro de disco cheio apareceria só no close, e o upload
    // teria sido reportado como sucesso.
    arquivo
        .flush()
        .await
        .map_err(|e| (StatusCode::INSUFFICIENT_STORAGE, e.to_string()))?;

    Ok(total.to_string())
}

async fn save_file(Json(payload): Json<SaveRequest>) -> String {
    match fs::write(&payload.path, &payload.content) {
        Ok(_) => "Salvo com sucesso!".to_string(),
        Err(e) => format!("Erro ao salvar: {}", e),
    }
}