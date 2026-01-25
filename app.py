import os
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, Response
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY is not set in environment variables")

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600
)

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]

# YouTubeのカテゴリIDを名前に変換するマップ（主要なもの）
CATEGORY_MAP = {
    "1": "映画/アニメ", "2": "自動車", "10": "音楽", "15": "ペット", "17": "スポーツ",
    "19": "旅行", "20": "ゲーム", "22": "ブログ", "23": "コメディ", "24": "エンタメ",
    "25": "ニュース", "26": "ハウツー", "27": "教育", "28": "科学/技術", "29": "非営利"
}

# --- 静的ファイル配信 ---
def get_physical_file(filename, mimetype):
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        with open(path, "rb") as f:
            content = f.read()
            return Response(content, mimetype=mimetype)
    return f"{filename} not found", 404

@app.route('/')
def index():
    return get_physical_file('index.html', 'text/html')

@app.route('/script.js')
def serve_js():
    return get_physical_file('script.js', 'application/javascript')

# --- 認証関連 ---
def get_flow():
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
    flow = google_auth_oauthlib.flow.Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow

def build_youtube_service():
    if 'credentials' not in session: return None
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route('/login')
def login():
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow = get_flow()
    authorization_response = request.url.replace('http://', 'https://')
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token, 'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri, 'client_id': credentials.client_id,
        'client_secret': credentials.client_secret, 'scopes': credentials.scopes
    }
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    return jsonify({"ok": 'credentials' in session})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- 高度なチャンネル取得機能 ---
@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
    
    all_subs = []
    try:
        next_page_token = None
        while True:
            subs_res = youtube.subscriptions().list(
                part="snippet,contentDetails", mine=True, maxResults=50, pageToken=next_page_token
            ).execute()
            
            items = subs_res.get('items', [])
            if not items: break

            channel_ids = [item['snippet']['resourceId']['channelId'] for item in items]
            
            # 統計情報とカテゴリ（ジャンル）を同時に取得
            chan_res = youtube.channels().list(
                part="statistics,snippet", id=",".join(channel_ids)
            ).execute()
            
            chan_info_map = {
                c['id']: {
                    "stats": c.get('statistics', {}),
                    "catId": c['snippet'].get('categoryId', "0")
                } for c in chan_res.get('items', [])
            }

            for item in items:
                c_id = item['snippet']['resourceId']['channelId']
                info = chan_info_map.get(c_id, {"stats": {}, "catId": "0"})
                
                all_subs.append({
                    "subscriptionId": item['id'],
                    "channelId": c_id,
                    "title": item['snippet']['title'],
                    "thumbnails": item['snippet']['thumbnails']['default']['url'],
                    "lastUploadDate": "pending",
                    "subscribers": int(info['stats'].get('subscriberCount', 0)),
                    "videoCount": int(info['stats'].get('videoCount', 0)),
                    "category": CATEGORY_MAP.get(info['catId'], "その他")
                })
            
            next_page_token = subs_res.get('nextPageToken')
            if not next_page_token: break
                
        return jsonify(all_subs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 個別分析（並列リクエストをフロントから受ける）
@app.route('/api/analyze', methods=['POST'])
def analyze():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
    c_id = request.get_json().get('channelId')
    try:
        c_res = youtube.channels().list(part="contentDetails", id=c_id).execute()
        uploads_id = c_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        p_res = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=1).execute()
        date = p_res["items"][0]["snippet"]["publishedAt"] if p_res.get("items") else "none"
        return jsonify({"channelId": c_id, "lastUploadDate": date})
    except:
        return jsonify({"lastUploadDate": "none"})

# バッチ削除処理（1件ずつ丁寧に処理）
@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
    ids = request.get_json().get('subscriptionIds', [])
    results = {"success": 0, "fail": 0, "details": []}
    for s_id in ids:
        try:
            youtube.subscriptions().delete(id=s_id).execute()
            results["success"] += 1
        except Exception as e:
            results["fail"] += 1
            results["details"].append({"id": s_id, "error": str(e)})
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True)
