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

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY must be set in environment variables")

# Render等のHTTPS環境でのセッション維持設定
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# Google Cloud Consoleの設定
CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": [os.getenv("REDIRECT_URI")]
    }
}

def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

def build_youtube_service():
    if 'credentials' not in session:
        return None
    # 修正箇所: 正しいインポートパスでCredentialsを復元
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/auth/google')
def authorize():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('callback', _external=True, _scheme='https')
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/auth/callback')
def callback():
    state = session.get('state')
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = url_for('callback', _external=True, _scheme='https')
    
    authorization_response = request.url.replace('http:', 'https:')
    flow.fetch_token(authorization_response=authorization_response)
    
    session['credentials'] = credentials_to_dict(flow.credentials)
    return redirect('/')

@app.route('/logout')
def logout():
    # 指摘事項への対応: データの削除
    session.clear()
    return redirect('/')

@app.route('/api/auth/status')
def auth_status():
    if 'credentials' in session:
        return jsonify({"authenticated": True})
    return jsonify({"authenticated": False}), 401

@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    
    all_subscriptions = []
    next_page_token = None
    
    try:
        while True:
            # 登録チャンネルを最大50件ずつ取得（シークバーの元データ）
            req = youtube.subscriptions().list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            )
            res = req.execute()
            
            for item in res.get('items', []):
                all_subscriptions.append({
                    "subscriptionId": item['id'],
                    "channelId": item['snippet']['resourceId']['channelId'],
                    "title": item['snippet']['title'],
                    "thumbnails": item['snippet']['thumbnails']['default']['url'],
                    "lastUploadDate": "pending", # フロントエンドの分析待ち状態
                    "isSubscribed": True
                })
            
            next_page_token = res.get('nextPageToken')
            if not next_page_token:
                break
        return jsonify(all_subscriptions)
    except Exception as e:
        # ここでエラーが起きると500エラーになるためログ出力
        print(f"Error in all-channels: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_channel():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.get_json()
    channel_id = data.get('channelId')
    
    try:
        # 最新動画投稿日を取得（休止中判定のコアロジック）
        channel_res = youtube.channels().list(
            part="contentDetails", id=channel_id
        ).execute()
        
        uploads_id = channel_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist_res = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=1
        ).execute()
        
        last_date = "none"
        if playlist_res.get("items"):
            last_date = playlist_res["items"][0]["snippet"]["publishedAt"]
        
        return jsonify({"channelId": channel_id, "lastUploadDate": last_date})
    except:
        return jsonify({"lastUploadDate": "none"})

# あなたが重視する「一括解除」機能
@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.get_json()
    ids = data.get('subscriptionIds', [])
    success, fail = 0, 0
    
    for sub_id in ids:
        try:
            youtube.subscriptions().delete(id=sub_id).execute()
            success += 1
        except Exception:
            fail += 1
            
    return jsonify({"successCount": success, "failCount": fail})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
