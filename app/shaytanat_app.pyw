"""Шайтанат — узбекско-русский параллельный корпус (приложение).

Запуск: двойной щелчок по этому файлу (нужен Python 3.9+) или по Shaytanat.exe.
Открывает окно приложения (Microsoft Edge или Google Chrome в режиме приложения,
иначе браузер по умолчанию). Работает без интернета; интернет нужен только переводчику,
который обращается к серверу перевода по ключу API, сохранённому на этом компьютере.
Только стандартная библиотека Python.
"""
import json, os, sys, time, threading, subprocess, webbrowser, urllib.request, urllib.error, http.client, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP_ID = 'shaytanat'
VERSION = '1.1 (23.10.2026)'
PORT = 8765
BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(BASE, 'web', 'index.html')
CFG_DIR = os.path.join(os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), '.config'), 'Shaytanat')
CFG = os.path.join(CFG_DIR, 'config.json')
API = 'https://api.anthropic.com/v1/messages'
MODELS = {'opus': ('claude-opus-5-5', 'Opus'), 'sonnet': ('claude-sonnet-5-5', 'Sonnet')}
IDLE_LIMIT = 180          # секунд без сигнала от окна, после которых приложение закрывается
FIRST_WAIT = 300          # сколько ждать первого сигнала от окна

state = {'last_ping': None, 'bye': None, 'started': time.time()}


def log(msg):
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(os.path.join(CFG_DIR, 'log.txt'), 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def load_cfg():
    try:
        with open(CFG, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cfg(cfg):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False)


def get_key():
    return (load_cfg().get('api_key') or '').strip()


def key_hint(k):
    return ('…' + k[-4:]) if k else ''


def clean_output(text, src):
    """Как в пилоте: если модель добавила к переводу рассуждение, взять итоговый вариант (последний абзац)."""
    if '\n' in src.strip():
        return text
    parts = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    return parts[-1] if len(parts) > 1 else text


def translate(model, system, user):
    key = get_key()
    if not key:
        return 400, {'error': 'Ключ API не задан. Вставьте ключ в поле «Ключ API» и нажмите «Сохранить ключ».'}
    if model not in MODELS:
        return 400, {'error': 'Неизвестная модель.'}
    model_id, label = MODELS[model]
    body = {'model': model_id, 'max_tokens': 1024, 'system': system,
            'messages': [{'role': 'user', 'content': user}], 'temperature': 0.2}
    headers = {'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
    for attempt in range(4):
        req = urllib.request.Request(API, data=json.dumps(body).encode('utf-8'), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode('utf-8'))
            text = ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text').strip()
            src = user.rsplit('Предложение для перевода:\n', 1)[-1]
            return 200, {'text': clean_output(text, src), 'raw': text, 'model': label}
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'ignore')
            if e.code == 400 and 'temperature' in msg and 'temperature' in body:
                body.pop('temperature'); continue
            if e.code in (401, 403):
                return e.code, {'error': 'Ключ API не принят. Проверьте, что ключ скопирован целиком.'}
            if 'credit balance' in msg.lower():
                return 402, {'error': 'На счёте, к которому привязан ключ API, закончились средства.'}
            if e.code in (429, 500, 503, 529) and attempt < 3:
                time.sleep(5 * (attempt + 1)); continue
            log(f'API {e.code}: {msg[:500]}')
            return 502, {'error': f'Сервер перевода вернул ошибку {e.code}. Попробуйте позже.'}
        except (OSError, http.client.HTTPException) as e:
            if attempt < 3:
                time.sleep(3); continue
            log(f'net: {e!r}')
            return 502, {'error': 'Нет связи с сервером перевода. Проверьте интернет.'}
    return 502, {'error': 'Сервер перевода не ответил. Попробуйте позже.'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Shaytanat'

    def log_message(self, *a):
        pass

    def _host_ok(self):
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def _send(self, code, obj=None, raw=None, ctype='application/json; charset=utf-8'):
        data = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 2_000_000:
            return None
        try:
            return json.loads(self.rfile.read(n).decode('utf-8') or '{}')
        except ValueError:
            return None

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {'error': 'forbidden'})
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            with open(PAGE, 'rb') as f:
                return self._send(200, raw=f.read(), ctype='text/html; charset=utf-8')
        if path == '/api/status':
            k = get_key()
            return self._send(200, {'app': APP_ID, 'version': VERSION, 'has_key': bool(k), 'key_hint': key_hint(k)})
        if path == '/api/ping':
            state['last_ping'] = time.time(); state['bye'] = None
            return self._send(200, {'ok': True})
        return self._send(404, {'error': 'not found'})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {'error': 'forbidden'})
        path = self.path.split('?')[0]
        if path == '/api/bye':
            state['bye'] = time.time()
            return self._send(200, {'ok': True})
        b = self._body()
        if b is None:
            return self._send(400, {'error': 'Неверный запрос.'})
        if path == '/api/key':
            k = str(b.get('key', '')).strip().strip('"').strip("'")
            cfg = load_cfg()
            if not k:
                cfg.pop('api_key', None); save_cfg(cfg)
                return self._send(200, {'has_key': bool(get_key()), 'key_hint': key_hint(get_key())})
            if not k.startswith('sk-') or len(k) < 30 or any(c.isspace() for c in k):
                return self._send(400, {'error': 'Это не похоже на ключ API: проверьте, что он скопирован целиком и без пробелов.'})
            cfg['api_key'] = k; save_cfg(cfg)
            return self._send(200, {'has_key': True, 'key_hint': key_hint(k)})
        if path == '/api/translate':
            code, res = translate(str(b.get('model', '')).lower(), str(b.get('system', '')), str(b.get('user', '')))
            return self._send(code, res)
        return self._send(404, {'error': 'not found'})


def find_browser():
    if os.name != 'nt':
        return None
    pf = [os.environ.get(v, '') for v in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA')]
    cands = []
    for base in pf:
        if base:
            cands += [os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                      os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')]
    return next((c for c in cands if os.path.isfile(c)), None)


def open_window(url):
    exe = find_browser()
    if exe:
        try:
            subprocess.Popen([exe, f'--app={url}', '--window-size=1400,900'], close_fds=True)
            return
        except OSError as e:
            log(f'browser: {e!r}')
    webbrowser.open(url)


def existing_instance(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=2) as r:
            return json.loads(r.read().decode('utf-8')).get('app') == APP_ID
    except Exception:
        return False


def watchdog(srv):
    while True:
        time.sleep(3)
        now = time.time()
        lp, bye = state['last_ping'], state['bye']
        if bye and now - bye > 8:
            break                                   # окно закрыто и не открылось снова
        if lp is None and now - state['started'] > FIRST_WAIT:
            break
        if lp is not None and now - lp > IDLE_LIMIT:
            break
    log('exit (window closed)')
    srv.shutdown()


def main():
    args = sys.argv[1:]
    port = PORT
    if '--port' in args:
        port = int(args[args.index('--port') + 1])
    no_window = '--no-window' in args
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except OSError:
        if existing_instance(port):
            if not no_window:
                open_window(f'http://127.0.0.1:{port}/')
            return
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = f'http://127.0.0.1:{srv.server_address[1]}/'
    log(f'start {VERSION} {url}')
    if not no_window:
        threading.Timer(0.3, open_window, args=(url,)).start()
        threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
    srv.serve_forever()


if __name__ == '__main__':
    main()
