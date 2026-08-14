import streamlit as st
import streamlit.components.v1 as components
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import random
import time
import urllib.request
import urllib.parse
import re
import json

NG_WORDS = ["ばか", "あほ", "死ね", "殺す", "うんこ", "ちんこ", "アホ", "バカ", "カス", "ゴミ", "クソ"]
import httpx

# httpx 0.28.0+ compatibility patch for youtube-search-python
if not hasattr(httpx, '_patched_for_yt'):
    original_post = httpx.post
    original_get = httpx.get
    def patched_post(*args, **kwargs):
        if 'proxies' in kwargs:
            del kwargs['proxies']
        return original_post(*args, **kwargs)
    def patched_get(*args, **kwargs):
        if 'proxies' in kwargs:
            del kwargs['proxies']
        return original_get(*args, **kwargs)
    httpx.post = patched_post
    httpx.get = patched_get
    httpx._patched_for_yt = True

from youtubesearchpython import VideosSearch

# ==========================================
# 1. ページ設定とAndroid(スマホ)向け最適化
# ==========================================
st.set_page_config(
    page_title="Song Requests",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed"
)

components.html("""
<script>
    const head = window.parent.document.head;
    if (!head.querySelector('meta[name="mobile-web-app-capable"]')) {
        let meta = document.createElement('meta');
        meta.name = "mobile-web-app-capable";
        meta.content = "yes";
        head.appendChild(meta);
        
        let metaApple = document.createElement('meta');
        metaApple.name = "apple-mobile-web-app-capable";
        metaApple.content = "yes";
        head.appendChild(metaApple);
        
        let metaViewport = head.querySelector('meta[name="viewport"]');
        if(metaViewport) {
            metaViewport.content = "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no";
        }
    }
</script>
""", height=0, width=0)

st.markdown("""
<style>
    /* 右上の不要なボタン（Share, GitHubなど）とヘッダーを非表示 */
    [data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {
        display: none !important;
        visibility: hidden !important;
    }
    
    .stTextInput>div>div>input {
        font-size: 18px !important;
        padding: 12px !important;
    }
    .stButton>button {
        width: 100% !important;
        min-height: 60px !important;
        font-size: 18px !important;
        font-weight: bold !important;
        border-radius: 10px !important;
        margin-top: 10px !important;
        margin-bottom: 10px !important;
        white-space: normal !important;
        word-wrap: break-word !important;
    }
    .request-card {
        background-color: #1e1e1e;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #1DB954;
        margin-bottom: 15px;
    }
    .request-title {
        font-size: 20px;
        font-weight: bold;
        color: #ffffff;
        margin-bottom: 5px;
    }
    .request-artist {
        font-size: 16px;
        color: #b3b3b3;
        margin-bottom: 10px;
    }
    .request-meta {
        font-size: 12px;
        color: #888888;
    }
    /* YouTube検索結果のタイトル用 */
    .yt-title {
        font-size: 18px;
        font-weight: bold;
        color: #ffffff;
        margin-bottom: 5px;
    }
    .yt-channel {
        font-size: 14px;
        color: #b3b3b3;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. データベース設定 (SQLite)
# ==========================================
DB_FILE = 'requests.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS song_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            song_title TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            youtube_url TEXT,
            status TEXT DEFAULT 'Pending'
        )
    ''')
    try:
        c.execute("ALTER TABLE song_requests ADD COLUMN handle_name TEXT DEFAULT '名無し'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE song_requests ADD COLUMN comment TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS ng_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE
        )
    ''')
    c.execute("SELECT COUNT(*) FROM ng_words")
    if c.fetchone()[0] == 0:
        initial_words = ["ばか", "あほ", "死ね", "殺す", "うんこ", "ちんこ", "アホ", "バカ", "カス", "ゴミ", "クソ"]
        for word in initial_words:
            c.execute("INSERT OR IGNORE INTO ng_words (word) VALUES (?)", (word,))
            
    conn.commit()
    conn.close()

def get_ng_words():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, word FROM ng_words ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def add_ng_word(word):
    if not word.strip(): return False
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO ng_words (word) VALUES (?)", (word.strip(),))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def delete_ng_word(word_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM ng_words WHERE id = ?", (word_id,))
    conn.commit()
    conn.close()

def add_request(handle, title, artist, url, comment):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO song_requests (handle_name, song_title, artist_name, youtube_url, comment) VALUES (?, ?, ?, ?, ?)", (handle, title, artist, url, comment))
    conn.commit()
    conn.close()

def get_pending_requests():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("SELECT id, timestamp, handle_name, song_title, artist_name, youtube_url, comment FROM song_requests WHERE status = 'Pending' ORDER BY timestamp ASC")
    except sqlite3.OperationalError:
        c.execute("SELECT id, timestamp, handle_name, song_title, artist_name, youtube_url, '' as comment FROM song_requests WHERE status = 'Pending' ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_played_requests():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("SELECT id, timestamp, handle_name, song_title, artist_name, youtube_url, comment FROM song_requests WHERE status = 'Played' ORDER BY timestamp DESC")
    except sqlite3.OperationalError:
        c.execute("SELECT id, timestamp, handle_name, song_title, artist_name, youtube_url, '' as comment FROM song_requests WHERE status = 'Played' ORDER BY timestamp DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_requests_for_download():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("SELECT timestamp, handle_name, song_title, artist_name, comment, status, youtube_url FROM song_requests ORDER BY timestamp ASC")
    except sqlite3.OperationalError:
        c.execute("SELECT timestamp, handle_name, song_title, artist_name, '' as comment, status, youtube_url FROM song_requests ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    
    csv_text = "リクエスト日時,ハンドルネーム,曲名,アーティスト名,コメント,ステータス,YouTubeリンク\n"
    for r in rows:
        row_data = [str(x).replace(',', '，') for x in r]
        csv_text += ",".join(row_data) + "\n"
    return csv_text.encode('utf-8-sig')

def update_status(req_id, new_status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE song_requests SET status = ? WHERE id = ?", (new_status, req_id))
    conn.commit()
    conn.close()

def check_rate_limit_db(handle_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM song_requests WHERE handle_name = ? AND timestamp >= datetime('now', '-3 minutes')", (handle_name,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

init_db()

# ==========================================
# 2.5 日替わりパスワード自動生成とメール送信
# ==========================================
@st.cache_resource
def get_daily_password_and_notify(date_str):
    """日替わりパスワード(数字4桁)を生成し、Gmail経由で管理者に送信する"""
    daily_pw = f"{random.randint(0, 9999):04d}"
    
    try:
        if "email" in st.secrets:
            sender_email = st.secrets["email"]["sender"]
            app_password = st.secrets["email"]["password"]
            receiver_email = st.secrets["email"]["receiver"]
            
            msg = MIMEText(f"本日のDJパネル パスワードは【 {daily_pw} 】です。\n不正アクセスを防ぐため、他者には教えないでください。")
            msg['Subject'] = f"【DJアプリ】本日のパスワード ({date_str})"
            msg['From'] = sender_email
            msg['To'] = receiver_email
            
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(sender_email, app_password)
            server.send_message(msg)
            server.quit()
            print(f"[{date_str}] パスワード通知メールを送信しました。")
    except Exception as e:
        print(f"メール送信エラー: {e}")
        pass
        
    return daily_pw

today_str = datetime.now().strftime("%Y-%m-%d")
ADMIN_PASSWORD = get_daily_password_and_notify(today_str)

def contains_ng_word(text):
    if not text: return False
    ng_words_list = get_ng_words()
    for _, word in ng_words_list:
        if word in text:
            return True
    return False

# ==========================================
# 3. セッションステート管理（状態の保持）
# ==========================================
if 'step' not in st.session_state:
    st.session_state.step = 'input'
if 'search_query' not in st.session_state:
    st.session_state.search_query = ''
if 'search_artist' not in st.session_state:
    st.session_state.search_artist = ''
if 'search_comment' not in st.session_state:
    st.session_state.search_comment = ''
if 'search_handle' not in st.session_state:
    st.session_state.search_handle = ''
if 'search_obj' not in st.session_state:
    st.session_state.search_obj = None
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'fallback_all_results' not in st.session_state:
    st.session_state.fallback_all_results = []
if 'fallback_index' not in st.session_state:
    st.session_state.fallback_index = 5
if 'last_request_time' not in st.session_state:
    st.session_state.last_request_time = 0
if 'is_admin_logged_in' not in st.session_state:
    st.session_state.is_admin_logged_in = False
if 'login_failed_count' not in st.session_state:
    st.session_state.login_failed_count = 0
if 'lockout_until' not in st.session_state:
    st.session_state.lockout_until = 0

def fallback_search(query, limit=5):
    try:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req).read().decode('utf-8')
        m = re.search(r'ytInitialData\s*=\s*({.+?});\s*</script>', html)
        if not m: return []
        data = json.loads(m.group(1))
        
        videos = []
        def extract(obj):
            if len(videos) >= limit: return
            if isinstance(obj, dict):
                if 'videoRenderer' in obj:
                    v = obj['videoRenderer']
                    title = v.get('title', {}).get('runs', [{}])[0].get('text', 'Unknown')
                    channel = v.get('ownerText', {}).get('runs', [{}])[0].get('text', 'Unknown')
                    vid = v.get('videoId', '')
                    thumbs = v.get('thumbnail', {}).get('thumbnails', [{'url': ''}])
                    thumb = thumbs[0]['url'] if thumbs else ''
                    if vid and title:
                        videos.append({
                            'id': vid,
                            'title': title,
                            'channel': {'name': channel},
                            'link': f'https://www.youtube.com/watch?v={vid}',
                            'thumbnails': [{'url': thumb}]
                        })
                for k, val in obj.items():
                    extract(val)
            elif isinstance(obj, list):
                for item in obj:
                    extract(item)
                    
        extract(data)
        return videos
    except Exception as e:
        print("Fallback search error:", e)
        return []

def perform_search(query, artist, comment):
    full_query = f"{query} {artist}".strip()
    st.session_state.search_obj = VideosSearch(full_query, limit=5)
    results = st.session_state.search_obj.result().get('result', [])
    
    if not results:
        all_fallback = fallback_search(full_query, limit=30)
        st.session_state.search_obj = None
        st.session_state.fallback_all_results = all_fallback
        st.session_state.fallback_index = 5
        results = all_fallback[:5]
        
    st.session_state.search_results = results
    st.session_state.step = 'results'
    st.session_state.search_query = query
    st.session_state.search_artist = artist
    st.session_state.search_comment = comment

def load_more():
    if st.session_state.search_obj:
        st.session_state.search_obj.next()
        st.session_state.search_results.extend(st.session_state.search_obj.result()['result'])
    else:
        idx = st.session_state.fallback_index
        next_results = st.session_state.fallback_all_results[idx : idx + 5]
        if next_results:
            st.session_state.search_results.extend(next_results)
            st.session_state.fallback_index += 5

def submit_request(handle, title, artist, url, comment):
    add_request(handle, title, artist, url, comment)
    st.session_state.step = 'success'

def reset_form():
    st.session_state.step = 'input'
    st.session_state.search_query = ''
    st.session_state.search_artist = ''
    st.session_state.search_comment = ''
    st.session_state.search_handle = ''
    st.session_state.search_obj = None
    st.session_state.search_results = []
    st.session_state.fallback_all_results = []
    st.session_state.fallback_index = 5

# ==========================================
# 4. アプリケーション本体
# ==========================================
PIN_CODE = ADMIN_PASSWORD[:4]

if not st.session_state.is_admin_logged_in:
    # 一般ユーザーにはサイドバー展開ボタン(>>)を完全に隠すCSSを適用
    st.markdown("""
    <style>
        [data-testid="collapsedControl"] { display: none !important; }
        [data-testid="stSidebar"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)
    
    # --- 管理者ログイン専用画面 (?admin=777 の場合) ---
    if st.query_params.get("admin") == "777":
        st.title("🎧 DJ Login")
        st.write("パスワードを入力してDJパネルを開きます。")
        
        current_time = time.time()
        if current_time < st.session_state.lockout_until:
            remaining = int(st.session_state.lockout_until - current_time)
            st.error(f"⚠️ ロックされています。\nあと {remaining}秒 お待ちください。")
            time.sleep(1)
            st.rerun()
        else:
            if st.session_state.login_failed_count >= 3:
                st.session_state.login_failed_count = 0
                
            admin_password = st.text_input("4桁のPINコードを入力", type="password", key="pin_login")
            if st.button("🔑 ログイン", use_container_width=True):
                if admin_password.strip() == PIN_CODE:
                    st.session_state.is_admin_logged_in = True
                    st.session_state.login_failed_count = 0
                    st.session_state.lockout_until = 0
                    st.rerun()
                else:
                    st.session_state.login_failed_count += 1
                    if st.session_state.login_failed_count >= 3:
                        st.session_state.lockout_until = time.time() + 60
                        st.error("⚠️ 3回間違えたため、1分間ロックされます。")
                    else:
                        st.error(f"PINコードが違います。(残り {3 - st.session_state.login_failed_count} 回)")
            
            st.divider()
            st.write("※パスワード再送信 (店長・責任者用)")
            resend_pw = st.text_input("再送信用 固定パスワード(4桁)を入力", type="password", key="resend_pw_input")
            if st.button("📧 新しいパスワードをメール送信", use_container_width=True):
                if resend_pw == "1030":
                    get_daily_password_and_notify.clear()
                    st.success("新しいパスワードをメールへ送信しました！")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error("固定パスワードが違います")
                    
        st.stop()  # ログイン画面の場合はここで処理を終了し、下の一般ユーザー画面を表示しない
        
    # ---------- 一般ユーザー画面 ----------
    st.title("🎵 曲リクエスト")
    
    if st.session_state.step == 'input':
        st.write("曲名からYouTubeを検索してリクエストします。")
        handle_name = st.text_input("ハンドルネーム (必須)", value=st.session_state.search_handle)
        song_title = st.text_input("曲名 (必須)", value=st.session_state.search_query)
        artist_name = st.text_input("アーティスト名 (任意)", value=st.session_state.search_artist)
        user_comment = st.text_area("コメント (120文字以内・任意)", value=st.session_state.search_comment, max_chars=120)
        
        if st.button("🔍 YouTubeで検索する", use_container_width=True):
            if not handle_name.strip() or not song_title.strip():
                st.error("ハンドルネームと曲名は必須です。")
            elif contains_ng_word(handle_name) or contains_ng_word(song_title) or contains_ng_word(artist_name) or contains_ng_word(user_comment):
                st.error("入力内容に不適切な表現が含まれているため検索できません。")
            else:
                st.session_state.search_handle = handle_name
                with st.spinner("検索中..."):
                    perform_search(song_title, artist_name, user_comment)
                st.rerun()

    elif st.session_state.step == 'results':
        st.write("以下の候補からリクエストしたい曲を選んでください。")
        
        if st.button("⬅️ 検索画面に戻る", use_container_width=True):
            st.session_state.step = 'input'
            st.rerun()
            
        st.divider()
        
        for video in st.session_state.search_results:
            title = video.get('title', 'Unknown Title')
            channel = video.get('channel', {}).get('name', 'Unknown Channel')
            url = video.get('link', '')
            thumbnails = video.get('thumbnails', [])
            thumb_url = thumbnails[0]['url'] if thumbnails else ''
            
            col1, col2 = st.columns([1, 1.5])
            with col1:
                if thumb_url:
                    st.image(thumb_url, use_container_width=True)
            with col2:
                st.markdown(f'<div class="yt-title">{title}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="yt-channel">{channel}</div>', unsafe_allow_html=True)
                if st.button("✨ リクエスト", key=f"req_{video['id']}", use_container_width=True):
                    final_artist = st.session_state.search_artist if st.session_state.search_artist.strip() else channel
                    handle = st.session_state.search_handle
                    comment = st.session_state.search_comment
                    
                    if contains_ng_word(handle) or contains_ng_word(title) or contains_ng_word(final_artist) or contains_ng_word(comment):
                        st.error("不適切な表現が含まれているため送信できません。入力内容を見直してください。")
                    else:
                        current_time = time.time()
                        time_diff = current_time - st.session_state.last_request_time
                        
                        if time_diff < 180 or check_rate_limit_db(handle):
                            remaining = int(180 - time_diff) if time_diff < 180 else 180
                            st.warning(f"連投は制限されています。あと約{remaining}秒お待ちいただくか、時間をおいて再度お試しください。")
                        else:
                            submit_request(handle, title, final_artist, url, comment)
                            st.session_state.last_request_time = time.time()
                            st.rerun()
            
            with st.expander("▶️ 試聴する（動画を再生）"):
                if url:
                    try:
                        st.video(url)
                    except Exception:
                        st.warning("動画の読み込みに失敗しました。")
            st.divider()
            
        if st.button("🔽 もっと見る（次の5件）", use_container_width=True):
            with st.spinner("読み込み中..."):
                load_more()
            st.rerun()
            
    elif st.session_state.step == 'success':
        st.success("🎉 リクエストを受け付けました！")
        st.balloons()
        if st.button("🔄 続けて別の曲をリクエストする", use_container_width=True):
            reset_form()
            st.rerun()



else:
    # ---------- DJ用 管理者画面 ----------
    st.sidebar.title("DJ Control")
    st.title("🎧 DJ Panel")
    
    if st.sidebar.button("🚪 ログアウト", use_container_width=True):
        st.session_state.is_admin_logged_in = False
        st.rerun()
        
    csv_data = get_all_requests_for_download()
    download_date_str = datetime.now().strftime("%Y%m%d")
    st.download_button(
        label="📥 全てのリクエスト履歴をダウンロード (Excel/CSV)",
        data=csv_data,
        file_name=f"{download_date_str}REQ.csv",
        mime="text/csv",
        use_container_width=True
    )
    
    try:
        import os
        manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DJリクエストシステム_マニュアル.txt")
        with open(manual_path, "r", encoding="utf-8") as f:
            manual_text = f.read()
        st.download_button(
            label="📘 システムマニュアルをダウンロード (.txt)",
            data=manual_text,
            file_name="DJリクエストシステム_マニュアル.txt",
            mime="text/plain",
            use_container_width=True
        )
    except FileNotFoundError:
        pass
    
    with st.expander("⚙️ NGワード設定（荒らし対策）", expanded=False):
        st.write("現在登録されているNGワード一覧:")
        current_ng_words = get_ng_words()
        
        if not current_ng_words:
            st.info("NGワードは登録されていません。")
            
        for ng_id, ng_word in current_ng_words:
            c1, c2 = st.columns([4, 1])
            with c1:
                st.write(f"🚫 {ng_word}")
            with c2:
                if st.button("🗑️", key=f"del_ng_{ng_id}", use_container_width=True):
                    delete_ng_word(ng_id)
                    st.rerun()
        
        st.divider()
        new_ng_word = st.text_input("新しいNGワードを追加", key="new_ng_word_input")
        if st.button("➕ NGワードを追加", use_container_width=True):
            if new_ng_word:
                if add_ng_word(new_ng_word):
                    st.success(f"「{new_ng_word}」をNGワードに追加しました。")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("その言葉はすでに登録されています。")
    
    st.divider()
    
    admin_view = st.radio("表示するリスト", ["未プレイ (新着)", "プレイ済 (履歴)"], horizontal=True)
    
    if admin_view == "未プレイ (新着)":
        st.write("新着リクエスト一覧")
        requests = get_pending_requests()
        
        if not requests:
            st.info("現在、保留中のリクエストはありません。")
        
        for req in requests:
            req_id, timestamp, handle, title, artist, url, comment = req
            
            url_html = f'<div style="margin-top: 10px; font-size: 14px; word-break: break-all;"><a href="{url}" target="_blank" style="color: #1DB954;">🔗 YouTube URL: {url}</a></div>' if url else ""
            
            st.markdown(f"""
            <div class="request-card">
                <div class="request-title">{title}</div>
                <div class="request-artist">👤 {artist}</div>
                {url_html}
            </div>
            """, unsafe_allow_html=True)
                    
            col1, col2 = st.columns(2)
            with col1:
                if st.button("▶️ プレイ済", key=f"play_{req_id}", use_container_width=True):
                    update_status(req_id, 'Played')
                    st.rerun()
            with col2:
                if st.button("🗑️ アーカイブ", key=f"arch_{req_id}", use_container_width=True):
                    update_status(req_id, 'Archived')
                    st.rerun()
                    
            st.divider()
            
    else:
        st.write("プレイ済みのリクエスト履歴")
        requests = get_played_requests()
        
        if not requests:
            st.info("プレイ済みの履歴はありません。")
            
        for req in requests:
            req_id, timestamp, handle, title, artist, url, comment = req
            
            url_html = f'<div style="margin-top: 10px; font-size: 14px; word-break: break-all;"><a href="{url}" target="_blank" style="color: #1DB954;">🔗 YouTube URL: {url}</a></div>' if url else ""
            
            st.markdown(f"""
            <div class="request-card" style="border-left-color: #555555;">
                <div class="request-title">{title}</div>
                <div class="request-artist">👤 {artist}</div>
                {url_html}
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("↩️ 未プレイに戻す (誤操作の取消)", key=f"undo_{req_id}", use_container_width=True):
                update_status(req_id, 'Pending')
                st.rerun()
                
            st.divider()
