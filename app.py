import os
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# 環境変数の読み込み
load_dotenv()

# アプリの物理的な絶対パスを取得
# Render上では /opt/render/project/src などを指します
base_dir = os.path.dirname(os.path.abspath(__file__))

# static_folderをNoneに設定し、ルーティングで明示的に配信することで404を防ぐ
app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY is not set in environment variables")

# Render等のプロキシ環境でHTTPSを正しく扱うための設定
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600
)

# OAuth警告の抑制
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]

# --- 静的ファイル配信 (Not Found対策) ---

@app.route('/')
def index():
    """ルートアクセス時に index.html を確実に返す"""
    return send_from_directory(base_dir, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """script.js やその他のファイルをベースディレクトリから直接返す"""
    return send_from_directory(base_dir, filename)

# --- Google OAuth フロー ---

def get_flow():
    """環境変数からリダイレクトURIを読み込み、OAuthフローを生成"""
    redirect_uri = os.getenv("REDIRECT_URI")
    
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }
    
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        client_config,
        scopes=SCOPES
    )
    flow.redirect_uri = redirect_uri
    return flow

def build_youtube_service():
    if 'credentials' not in session:
        return None
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

# --- 認証エンドポイント ---

@app.route('/login')
def login():
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow = get_flow()
    # プロキシ経由で http になっている場合を考慮して置換
    authorization_response = request.url.replace('http://', 'https://')
    
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

@app.route('/api/auth/status')
def auth_status():
    return jsonify({"ok": 'credentials' in session})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- YouTube Data API 操作 ---

@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    
    all_subs = []
    try:
        next_page_token = None
        while True:
            subs_res = youtube.subscriptions().list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            items = subs_res.get('items', [])
            if not items: break

            channel_ids = [item['snippet']['resourceId']['channelId'] for item in items]
            
            # 統計情報（登録者数・動画本数）を一括取得
            stats_res = youtube.channels().list(
                part="statistics",
                id=",".join(channel_ids)
            ).execute()
            
            stats_map = {s['id']: s['statistics'] for s in stats_res.get('items', [])}

            for item in items:
                c_id = item['snippet']['resourceId']['channelId']
                stats = stats_map.get(c_id, {})
                
                all_subs.append({
                    "subscriptionId": item['id'],
                    "channelId": c_id,
                    "title": item['snippet']['title'],
                    "thumbnails": item['snippet']['thumbnails']['default']['url'],
                    "lastUploadDate": "pending",
                    "isSubscribed": True,
                    "isFavorite": False,
                    "subscribers": int(stats.get('subscriberCount', 0)),
                    "videoCount": int(stats.get('videoCount', 0))
                })
            
            next_page_token = subs_res.get('nextPageToken')
            if not next_page_token: break
                
        return jsonify(all_subs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    c_id = data.get('channelId')
    try:
        c_res = youtube.channels().list(part="contentDetails", id=c_id).execute()
        uploads_id = c_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        p_res = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=1).execute()
        date = p_res["items"][0]["snippet"]["publishedAt"] if p_res.get("items") else "none"
        return jsonify({"channelId": c_id, "lastUploadDate": date})
    except:
        return jsonify({"lastUploadDate": "none"})

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
    ids = request.get_json().get('subscriptionIds', [])
    success, fail = 0, 0
    for s_id in ids:
        try:
            youtube.subscriptions().delete(id=s_id).execute()
            success += 1
        except: fail += 1
    return jsonify({"successCount": success, "failCount": fail})

if __name__ == '__main__':
    app.run(debug=True)
