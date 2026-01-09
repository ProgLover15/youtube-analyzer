import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY must be set in environment variables")

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

# 読み取り専用スコープを優先（セキュリティ的に望ましい）
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly"
]

CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        # ここはデプロイ環境に合わせて動的に決まるため、コード内での固定は避けるか正しいURIを入れる
        "redirect_uris": [os.getenv("REDIRECT_URI", "http://127.0.0.1:5000/auth/callback")]
    }
}

def build_youtube_service():
    if 'credentials' not in session:
        return None
    from google.oauth2.credentials import Credentials
    credentials = Credentials(**session['credentials'])
    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# --- 認証ルート ---
@app.route('/auth/google')
def auth_google():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    
    # 外部URL（https）を正しく認識させるため _external=True を使用
    flow.redirect_uri = url_for('auth_callback', _external=True)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent' # 再ログイン時に確実に認証画面を出す（審査時に推奨される）
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/auth/callback')
def auth_callback():
    state = session.get('state')
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    
    flow.redirect_uri = url_for('auth_callback', _external=True)

    authorization_response = request.url
    # 本番環境(Render)でのhttps化を強制
    if authorization_response.startswith('http:'):
        authorization_response = authorization_response.replace('http:', 'https:', 1)

    flow.fetch_token(authorization_response=authorization_response)

    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect(url_for('index'))

# URLを index.html 内の呼び出し (/auth/logout) と一致させる
@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    if 'credentials' in session:
        return jsonify({"status": "authenticated"})
    return jsonify({"error": "Not authenticated"}), 401

# --- APIエンドポイント (中身は同じなので維持) ---
# ... (get_all_channels, analyze_channel, bulk_delete_subscriptions 等)
# ... ※変更がないため省略しますが、実ファイルではそのまま残してください。

if __name__ == '__main__':
    # 開発環境でOAuthを動かすために必要
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(debug=True, port=5000)
