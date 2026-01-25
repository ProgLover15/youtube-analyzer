import os
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# 環境変数の読み込み
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY is not set in environment variables")

# プロキシ設定（Render等のHTTPS環境でリダイレクトURIを正しく認識させるために必須）
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600
)

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
# 開発時のみ有効にする（本番環境では不要だが、OAuthのエラー詳細が見やすくなる）
# os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]

def get_flow():
    """OAuthフローオブジェクトを生成する（redirect_uriエラー防止用）"""
    redirect_uri = os.getenv("REDIRECT_URI")
    
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=SCOPES
    )
    flow.redirect_uri = redirect_uri
    return flow

def build_youtube_service():
    if 'credentials' not in session:
        return None
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/login')
def login():
    flow = get_flow()
    # prompt='consent' を入れることで、常にリフレッシュトークンを取得し直す
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow = get_flow()
    # Render等のプロキシ環境下でURLが http になるのを防ぐための処置
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

# 1. チャンネル一覧取得（統計データ込）
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

            # IDリストを作成して統計情報を一括取得
            channel_ids = [item['snippet']['resourceId']['channelId'] for item in items]
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

# 2. チャンネル分析
@app.route('/api/analyze', methods=['POST'])
def analyze():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    channel_id = data.get('channelId')
    
    try:
        c_res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        if not c_res.get("items"):
            return jsonify({"lastUploadDate": "none"})
            
        uploads_id = c_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        p_res = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=1).execute()
        
        date = "none"
        if p_res.get("items"):
            date = p_res["items"][0]["snippet"]["publishedAt"]
        
        return jsonify({"channelId": channel_id, "lastUploadDate": date})
    except Exception:
        return jsonify({"lastUploadDate": "none"})

# 3. 登録解除
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
        except Exception:
            fail += 1
            
    return jsonify({"successCount": success, "failCount": fail})

if __name__ == '__main__':
    app.run(debug=True)
