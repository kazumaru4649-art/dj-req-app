import streamlit as st
import streamlit.components.v1 as components
import sqlite3
from datetime import datetime
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
    conn.commit()
    conn.close()

def add_request(handle, title, artist, url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO song_requests (handle_name, song_title, artist_name, youtube_url) VALUES (?, ?, ?, ?)", (handle, title, artist, url))
    conn.commit()
    conn.close()

def get_pending_requests():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, handle_name, song_title, artist_name, youtube_url FROM song_requests WHERE status = 'Pending' ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_played_requests():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, handle_name, song_title, artist_name, youtube_url FROM song_requests WHERE status = 'Played' ORDER BY timestamp DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_requests_for_download():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT timestamp, handle_name, song_title, artist_name, status, youtube_url FROM song_requests ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    
    csv_text = "リクエスト日時,ハンドルネーム,曲名,アーティスト名,ステータス,YouTubeリンク\n"
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

init_db()

# ==========================================
# 3. セッションステート管理（状態の保持）
# ==========================================
if 'step' not in st.session_state:
    st.session_state.step = 'input'
if 'search_query' not in st.session_state:
    st.session_state.search_query = ''
if 'search_artist' not in st.session_state:
    st.session_state.search_artist = ''
if 'search_handle' not in st.session_state:
    st.session_state.search_handle = ''
if 'search_obj' not in st.session_state:
    st.session_state.search_obj = None
if 'search_results' not in st.session_state:
    st.session_state.search_results = []

def perform_search(query, artist):
    full_query = f"{query} {artist}".strip()
    st.session_state.search_obj = VideosSearch(full_query, limit=5)
    st.session_state.search_results = st.session_state.search_obj.result()['result']
    st.session_state.step = 'results'
    st.session_state.search_query = query
    st.session_state.search_artist = artist

def load_more():
    if st.session_state.search_obj:
        st.session_state.search_obj.next()
        st.session_state.search_results.extend(st.session_state.search_obj.result()['result'])

def submit_request(handle, title, artist, url):
    add_request(handle, title, artist, url)
    st.session_state.step = 'success'

def reset_form():
    st.session_state.step = 'input'
    st.session_state.search_query = ''
    st.session_state.search_artist = ''
    st.session_state.search_handle = ''
    st.session_state.search_obj = None
    st.session_state.search_results = []

# ==========================================
# 4. アプリケーション本体
# ==========================================
st.sidebar.title("DJ Control")
admin_password = st.sidebar.text_input("Password", type="password")

if admin_password != "dj4649":
    # ---------- 一般ユーザー画面 ----------
    st.title("🎵 曲リクエスト")
    
    if st.session_state.step == 'input':
        st.write("曲名からYouTubeを検索してリクエストします。")
        handle_name = st.text_input("ハンドルネーム (必須)", value=st.session_state.search_handle)
        song_title = st.text_input("曲名 (必須)", value=st.session_state.search_query)
        artist_name = st.text_input("アーティスト名 (任意)", value=st.session_state.search_artist)
        
        if st.button("🔍 YouTubeで検索する", use_container_width=True):
            if not handle_name.strip() or not song_title.strip():
                st.error("ハンドルネームと曲名は必須です。")
            else:
                st.session_state.search_handle = handle_name
                with st.spinner("検索中..."):
                    perform_search(song_title, artist_name)
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
                    st.image(thumb_url, use_column_width=True)
            with col2:
                st.markdown(f'<div class="yt-title">{title}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="yt-channel">{channel}</div>', unsafe_allow_html=True)
                if st.button("✨ リクエスト", key=f"req_{video['id']}", use_container_width=True):
                    final_artist = st.session_state.search_artist if st.session_state.search_artist.strip() else channel
                    submit_request(st.session_state.search_handle, title, final_artist, url)
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
    st.title("🎧 DJ Panel")
    
    csv_data = get_all_requests_for_download()
    st.download_button(
        label="📥 全てのリクエスト履歴をダウンロード (Excel/CSV)",
        data=csv_data,
        file_name="song_requests_history.csv",
        mime="text/csv",
        use_container_width=True
    )
    st.divider()
    
    admin_view = st.radio("表示するリスト", ["未プレイ (新着)", "プレイ済 (履歴)"], horizontal=True)
    
    if admin_view == "未プレイ (新着)":
        st.write("新着リクエスト一覧")
        requests = get_pending_requests()
        
        if not requests:
            st.info("現在、保留中のリクエストはありません。")
        
        for req in requests:
            req_id, timestamp, handle, title, artist, url = req
            
            st.markdown(f"""
            <div class="request-card">
                <div class="request-title">{title}</div>
                <div class="request-artist">👤 {artist}</div>
                <div class="request-meta">📛 依頼者: {handle} &nbsp;|&nbsp; 🕒 {timestamp}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if url and ("youtube.com" in url or "youtu.be" in url):
                try:
                    st.video(url)
                except Exception:
                    st.warning("動画の読み込みに失敗しました。")
                    
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
            req_id, timestamp, handle, title, artist, url = req
            
            st.markdown(f"""
            <div class="request-card" style="border-left-color: #555555;">
                <div class="request-title">{title}</div>
                <div class="request-artist">👤 {artist}</div>
                <div class="request-meta">📛 依頼者: {handle} &nbsp;|&nbsp; 🕒 {timestamp}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("↩️ 未プレイに戻す (誤操作の取消)", key=f"undo_{req_id}", use_container_width=True):
                update_status(req_id, 'Pending')
                st.rerun()
                
            st.divider()
