from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["mock-social"])

MOCK_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>社群動態牆 (Social Lab Sandbox)</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #09090b; color: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  </style>
</head>
<body class="min-h-screen pb-12">
  <!-- Top Navigation -->
  <header class="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur px-4 py-3 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-tr from-purple-600 to-pink-500 flex items-center justify-center font-bold text-white text-lg">IG</div>
      <div>
        <h1 class="font-bold text-sm sm:text-base tracking-tight" id="headerTitle">社群動態牆 (Social Lab)</h1>
        <span class="text-[10px] text-zinc-500 font-mono">Instagram-Style Sandbox</span>
      </div>
      <span class="hidden sm:inline-block text-[11px] bg-purple-950 text-purple-300 border border-purple-800 px-2 py-0.5 rounded-full font-mono">
        本機安全隔離 (Localhost Safe)
      </span>
    </div>

    <div class="flex items-center space-x-3">
      <!-- Language Toggle -->
      <div class="flex items-center bg-zinc-900 border border-zinc-800 rounded-lg p-0.5 text-xs font-mono">
        <button id="langZhBtn" onclick="setLang('zh')" class="px-2 py-0.5 rounded bg-purple-600 text-white font-bold">繁中</button>
        <button id="langEnBtn" onclick="setLang('en')" class="px-2 py-0.5 rounded text-zinc-400 hover:text-white">EN</button>
      </div>

      <div id="authStatus" class="flex items-center space-x-2 text-xs">
        <span id="currentUserLabel" class="text-zinc-400 font-mono">尚未登入</span>
        <button id="authBtn" onclick="toggleAuthModal()" class="px-3 py-1.5 rounded-md bg-purple-600 hover:bg-purple-500 font-medium text-white transition">
          登入 (Log In)
        </button>
      </div>
    </div>
  </header>

  <!-- Login Modal -->
  <div id="loginModal" class="hidden fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
    <div class="bg-zinc-900 border border-zinc-800 p-6 rounded-xl max-w-sm w-full shadow-2xl space-y-4">
      <div class="flex items-center justify-between border-b border-zinc-800 pb-2">
        <h2 class="text-sm font-bold text-zinc-200" id="modalTitle">帳號身分登入 (Account Login)</h2>
        <button onclick="toggleAuthModal()" class="text-zinc-500 hover:text-zinc-300 text-sm">✕</button>
      </div>
      <div class="space-y-3">
        <div>
          <label class="text-xs text-zinc-400 block mb-1 font-mono" id="labelUsername">帳號名稱 (Username)</label>
          <input id="username" type="text" value="admin" class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-xs text-zinc-200 focus:border-purple-500 outline-none font-mono">
        </div>
        <div>
          <label class="text-xs text-zinc-400 block mb-1 font-mono" id="labelPassword">密碼 (Password)</label>
          <input id="password" type="password" value="password123" class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-xs text-zinc-200 focus:border-purple-500 outline-none font-mono">
        </div>
        <button id="submitLogin" onclick="handleLogin()" class="w-full py-2 rounded bg-purple-600 hover:bg-purple-500 font-medium text-xs text-white mt-1">
          登入 (Log In)
        </button>
        <button onclick="toggleAuthModal()" class="w-full py-1 text-zinc-500 hover:text-zinc-300 text-xs">
          取消 (Cancel)
        </button>
      </div>
      <p id="loginError" class="text-xs text-red-400 mt-2 hidden font-mono"></p>
    </div>
  </div>

  <!-- Feed Container -->
  <main class="max-w-lg mx-auto mt-6 px-4 space-y-4">
    <div class="flex items-center justify-between bg-zinc-900 border border-zinc-800 p-3 rounded-xl text-xs font-mono">
      <span class="text-zinc-400" id="feedBannerText">動態牆沙盒 (Sandbox Feed)</span>
      <button onclick="seedPosts()" id="seedBtn" class="px-2.5 py-1 rounded bg-purple-900/60 hover:bg-purple-800/80 border border-purple-700 text-purple-200 transition text-[11px]">
        + 補充 6 筆示範貼文 (Seed Demo)
      </button>
    </div>
    <div id="feedContainer" class="space-y-6">
      <div class="text-center py-8 text-zinc-500 text-xs font-mono" id="loadingLabel">載入動態牆中 (Loading feed)...</div>
    </div>
  </main>

  <script>
    let currentLang = localStorage.getItem("social_lab_lang") || "zh";
    let token = localStorage.getItem("social_lab_token");
    let currentUser = JSON.parse(localStorage.getItem("social_lab_user") || "null");

    function setLang(lang) {
      currentLang = lang;
      localStorage.setItem("social_lab_lang", lang);
      document.getElementById("langZhBtn").className = lang === "zh" ? "px-2 py-0.5 rounded bg-purple-600 text-white font-bold" : "px-2 py-0.5 rounded text-zinc-400 hover:text-white";
      document.getElementById("langEnBtn").className = lang === "en" ? "px-2 py-0.5 rounded bg-purple-600 text-white font-bold" : "px-2 py-0.5 rounded text-zinc-400 hover:text-white";
      updateI18nLabels();
      updateAuthUI();
      loadFeed();
    }

    function updateI18nLabels() {
      const isZh = currentLang === "zh";
      document.getElementById("headerTitle").textContent = isZh ? "社群動態牆 (Social Lab)" : "Social Lab Sandbox";
      document.getElementById("modalTitle").textContent = isZh ? "帳號身分登入 (Account Login)" : "Account Login";
      document.getElementById("labelUsername").textContent = isZh ? "帳號名稱 (Username)" : "Username";
      document.getElementById("labelPassword").textContent = isZh ? "密碼 (Password)" : "Password";
      document.getElementById("submitLogin").textContent = isZh ? "登入 (Log In)" : "Log In";
      const seedBtn = document.getElementById("seedBtn");
      if (seedBtn) seedBtn.textContent = isZh ? "+ 補充 6 筆示範貼文 (Seed Demo)" : "+ Seed 6 Demo Posts";
      const banner = document.getElementById("feedBannerText");
      if (banner) banner.textContent = isZh ? "動態牆沙盒 (Sandbox Feed)" : "Sandbox Feed";
    }

    function updateAuthUI() {
      const isZh = currentLang === "zh";
      const label = document.getElementById("currentUserLabel");
      const btn = document.getElementById("authBtn");
      if (token && currentUser) {
        label.textContent = "@" + currentUser.username;
        btn.textContent = isZh ? "登出 (Log Out)" : "Log Out";
        btn.onclick = handleLogout;
        btn.className = "px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 font-medium text-xs text-zinc-300";
      } else {
        label.textContent = isZh ? "尚未登入" : "Not logged in";
        btn.textContent = isZh ? "登入 (Log In)" : "Log In";
        btn.onclick = toggleAuthModal;
        btn.className = "px-3 py-1.5 rounded-md bg-purple-600 hover:bg-purple-500 font-medium text-xs text-white";
      }
    }

    function toggleAuthModal() {
      const modal = document.getElementById("loginModal");
      modal.classList.toggle("hidden");
    }

    async function handleLogin() {
      const u = document.getElementById("username").value.trim();
      const p = document.getElementById("password").value.trim();
      const err = document.getElementById("loginError");
      err.classList.add("hidden");

      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: u, password: p })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Login failed");

        token = data.token;
        currentUser = data.user;
        localStorage.setItem("social_lab_token", token);
        localStorage.setItem("social_lab_user", JSON.stringify(currentUser));
        toggleAuthModal();
        updateAuthUI();
        loadFeed();
      } catch (e) {
        err.textContent = e.message;
        err.classList.remove("hidden");
      }
    }

    function handleLogout() {
      token = null;
      currentUser = null;
      localStorage.removeItem("social_lab_token");
      localStorage.removeItem("social_lab_user");
      updateAuthUI();
      loadFeed();
    }

    async function seedPosts() {
      const btn = document.getElementById("seedBtn");
      btn.disabled = true;
      btn.textContent = currentLang === "zh" ? "正在補充貼文..." : "Seeding...";
      try {
        const res = await fetch("/api/posts/seed", { method: "POST" });
        const data = await res.json();
        await loadFeed();
      } catch (e) {
        alert("Seed failed: " + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = currentLang === "zh" ? "+ 補充 6 筆示範貼文 (Seed Demo)" : "+ Seed 6 Demo Posts";
      }
    }

    async function loadFeed() {
      const container = document.getElementById("feedContainer");
      const isZh = currentLang === "zh";
      try {
        const headers = token ? { "Authorization": "Bearer " + token } : {};
        const res = await fetch("/api/posts", { headers });
        const posts = await res.json();

        container.innerHTML = "";
        posts.forEach(post => {
          const card = document.createElement("article");
          card.className = "bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden shadow-sm";
          card.setAttribute("data-post-id", post.id);

          const heartColor = post.has_liked ? "text-red-500 fill-red-500" : "text-zinc-400 hover:text-white";
          const likesSuffix = isZh ? "個讚 (likes)" : "likes";
          const methodLabel = isZh ? "寫入機制: SQLite WAL" : "Method: SQLite WAL";

          card.innerHTML = `
            <div class="p-3 flex items-center justify-between">
              <div class="flex items-center space-x-2">
                <img src="${post.author_avatar_url}" class="w-8 h-8 rounded-full border border-zinc-700 bg-zinc-800 flex-shrink-0" alt="avatar">
                <span class="font-semibold text-xs">@${post.author_username}</span>
              </div>
              <span class="text-xs text-zinc-500 font-mono">Post #${post.id}</span>
            </div>
            <div class="aspect-square bg-zinc-950 flex items-center justify-center overflow-hidden">
              <img src="${post.image_url}" class="w-full h-full object-cover" alt="post image" onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600'">
            </div>
            <div class="p-3 space-y-2">
              <div class="flex items-center justify-between">
                <button data-action="like" data-like-btn="${post.id}" onclick="toggleLike(${post.id}, ${post.has_liked})" class="flex items-center space-x-1.5 focus:outline-none transition group">
                  <svg class="w-6 h-6 transition-transform active:scale-125 ${heartColor}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="${post.has_liked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
                  </svg>
                  <span class="font-bold text-xs" id="likesCount-${post.id}">${post.likes_count} ${likesSuffix}</span>
                </button>
                <span class="text-[10px] text-zinc-500 font-mono">${methodLabel}</span>
              </div>
              <p class="text-xs break-words overflow-hidden whitespace-pre-wrap"><span class="font-bold mr-1">@${post.author_username}</span><span class="text-zinc-300">${post.caption}</span></p>
              <div class="text-[10px] text-zinc-500 font-mono">${new Date(post.created_at).toLocaleString()}</div>
            </div>
          `;
          container.appendChild(card);
        });
      } catch (e) {
        container.innerHTML = `<div class="p-4 bg-red-950/40 border border-red-800 text-red-300 rounded text-xs text-center font-mono">Failed to load feed: ${e.message}</div>`;
      }
    }

    async function toggleLike(postId, currentlyLiked) {
      if (!token) {
        toggleAuthModal();
        return;
      }
      const endpoint = currentlyLiked ? `/api/posts/${postId}/unlike` : `/api/posts/${postId}/like?method=BROWSER`;
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Authorization": "Bearer " + token }
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Action failed");
        loadFeed();
      } catch (e) {
        alert("Action failed: " + e.message);
      }
    }

    function setupWS() {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${window.location.host}/ws`);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "post_liked" || msg.type === "post_unliked") {
            const countEl = document.getElementById("likesCount-" + msg.data.post_id);
            if (countEl) {
              const suffix = currentLang === "zh" ? "個讚 (likes)" : "likes";
              countEl.textContent = msg.data.likes_count + " " + suffix;
            }
          }
        } catch (e) {}
      };
      ws.onclose = () => setTimeout(setupWS, 2000);
    }

    setLang(currentLang);
    setupWS();
  </script>
</body>
</html>
"""

@router.get("/mock-social", response_class=HTMLResponse)
def get_mock_social_page():
    return HTMLResponse(content=MOCK_HTML)
