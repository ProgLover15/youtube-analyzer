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

# Render等のプロキシ環境下でリダイレクトURI(https)を正しく認識させるために必須
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600
)

# 警告回避設定
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]

def get_flow():
    """
    リダイレクトURIエラーを防止するためのフロー生成関数
    """
    # .envから取得（環境変数に設定されていることが前提）
    redirect_uri = os.getenv("REDIRECT_URI")
    
    # client_config形式で明示的に redirect_uris を渡す
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]  # ここがリスト形式であることが重要
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

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/login')
def login():
    # flowを生成して認証URLへ飛ばす
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    # 帰ってきたときも同じ設定でflowを生成
    flow = get_flow()
    
    # プロキシ環境でURLがhttpに書き換わってしまうのを防ぐ
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

# --- YouTube操作API ---

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
            
            # 統計情報をまとめて取得
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
