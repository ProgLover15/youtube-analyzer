import os
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# HTTPS環境での安定動作設定
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600 # 1時間有効
)

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [os.getenv("REDIRECT_URI")]
    }
}

def build_youtube_service():
    if 'credentials' not in session:
        return None
    
    # セッションから認証情報を復元
    creds_data = session['credentials']
    creds = google.oauth2.credentials.Credentials(
        token=creds_data.get('token'),
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data.get('token_uri'),
        client_id=creds_data.get('client_id'),
        client_secret=creds_data.get('client_secret'),
        scopes=creds_data.get('scopes')
    )

    # トークンの有効期限が切れているかチェック（不安定さの解消）
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(google.auth.transport.requests.Request())
                # 更新されたトークンをセッションに再保存
                session['credentials'] = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes
                }
            except Exception:
                return None

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)
@app.route('/')
def index(): return send_from_directory('.', 'index.html')

@app.route('/auth/google')
def authorize():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('callback', _external=True, _scheme='https')
    auth_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(auth_url)

@app.route('/auth/callback')
def callback():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(CLIENT_SECRETS_FILE, scopes=SCOPES, state=session.get('state'))
    flow.redirect_uri = url_for('callback', _external=True, _scheme='https')
    flow.fetch_token(authorization_response=request.url.replace('http:', 'https:'))
    session['credentials'] = credentials_to_dict(flow.credentials)
    return redirect('/')

@app.route('/logout')
def logout():
    session.clear() # ポリシー遵守：データの破棄
    return redirect('/')

@app.route('/api/auth/status')
def auth_status():
    return jsonify({"authenticated": True}) if 'credentials' in session else (jsonify({"authenticated": False}), 401)

# 2. 分析：購読リスト取得
@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Auth fail"}), 401
    all_subs = []
    token = None
    try:
        while True:
            res = youtube.subscriptions().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
            for item in res.get('items', []):
                all_subs.append({
                    "subscriptionId": item['id'],
                    "channelId": item['snippet']['resourceId']['channelId'],
                    "title": item['snippet']['title'],
                    "thumbnails": item['snippet']['thumbnails']['default']['url'],
                    "lastUploadDate": "pending",
                    "isSubscribed": True
                })
            token = res.get('nextPageToken')
            if not token: break
        return jsonify(all_subs)
    except Exception as e: return jsonify({"error": str(e)}), 500

# 2. 分析：投稿日解析
@app.route('/api/analyze', methods=['POST'])
def analyze():
    youtube = build_youtube_service()
    c_id = request.get_json().get('channelId')
    try:
        c_res = youtube.channels().list(part="contentDetails", id=c_id).execute()
        up_id = c_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        p_res = youtube.playlistItems().list(part="snippet", playlistId=up_id, maxResults=1).execute()
        date = p_res["items"][0]["snippet"]["publishedAt"] if p_res.get("items") else "none"
        return jsonify({"lastUploadDate": date})
    except: return jsonify({"lastUploadDate": "none"})

# 4. 整理：一括解除
@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    youtube = build_youtube_service()
    ids = request.get_json().get('subscriptionIds', [])
    success, fail = 0, 0
    for s_id in ids:
        try:
            youtube.subscriptions().delete(id=s_id).execute()
            success += 1
        except: fail += 1
    return jsonify({"successCount": success, "failCount": fail})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

