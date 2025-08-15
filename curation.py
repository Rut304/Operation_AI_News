<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>ExhaustiveAI Admin</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 20px; }
    h1 { margin: 0 0 12px 0; }
    .bar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
    input[type="password"], input[type="text"], input[type="url"] { padding: 6px 8px; border:1px solid #ccc; border-radius:6px; }
    button { padding: 6px 10px; border:1px solid #999; background:#f7f7f7; border-radius:6px; cursor:pointer; }
    button:hover { background:#eee; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th, td { border-bottom: 1px solid #e5e5e5; padding: 8px; vertical-align: top; }
    th { text-align: left; background:#fafafa; }
    .small { font-size: 12px; color:#666; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 900px){ .grid { grid-template-columns: 1fr; } }
    .card { border:1px solid #ddd; border-radius:8px; padding:12px; }
    .row-controls { display:flex; gap:8px; flex-wrap: wrap; }
    .mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
  </style>
</head>
<body>
  <h1>ExhaustiveAI — Admin Panel</h1>
  <div class="bar">
    <label>Admin Password:</label>
    <input id="pw" type="password" placeholder="ADMIN_PASSWORD">
    <button onclick="savePw()">Set</button>
    <span class="small">Changes save to JSON; re-run <b>curation.py</b> to publish.</span>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Current Headlines</h2>
      <div id="items-status" class="small"></div>
      <table id="items">
        <thead>
          <tr>
            <th>Headline</th><th>Source URL</th><th>Image URL</th><th>Actions</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>

    <div class="card">
      <h2>Never List (ban domains)</h2>
      <div class="row-controls">
        <input id="ban-domain" type="text" placeholder="example.com">
        <button onclick="banDomain()">Add</button>
      </div>
      <ul id="banned-list"></ul>

      <hr>
      <h2>Custom Feeds</h2>
      <div class="row-controls">
        <input id="feed-url" type="url" placeholder="https://site.tld/feed.xml">
        <button onclick="addFeed()">Add</button>
      </div>
      <ul id="feeds-list"></ul>
    </div>
  </div>

<script>
let ADMIN_KEY = localStorage.getItem('x_admin_key') || '';

function savePw() {
  const val = document.getElementById('pw').value.trim();
  if(!val) { alert('Enter a password.'); return; }
  ADMIN_KEY = val;
  localStorage.setItem('x_admin_key', ADMIN_KEY);
  alert('Saved.');
}

async function api(path, config={}) {
  const headers = config.headers || {};
  headers['X-Admin-Key'] = ADMIN_KEY;
  const res = await fetch(path, { ...config, headers });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function el(tag, props={}, children=[]) {
  const n = document.createElement(tag);
  Object.entries(props).forEach(([k,v]) => (k in n) ? n[k]=v : n.setAttribute(k,v));
  children.forEach(c => n.appendChild(typeof c==='string'? document.createTextNode(c): c));
  return n;
}

async function loadState() {
  const data = await api('/api/state', { method:'GET' });
  renderItems(data.items || []);
  renderBanned(data.banned_domains || []);
  renderFeeds(data.custom_feeds || []);
  document.getElementById('items-status').textContent = `${(data.items||[]).length} items (from curated_items.json)`;
}

function renderItems(items) {
  const tb = document.querySelector('#items tbody');
  tb.innerHTML = '';
  items.forEach(item => {
    const tr = el('tr');
    const headline = el('input', {type:'text', value:item.headline || ''});
    const url = el('input', {type:'url', value:item.url || ''});
    const img = el('input', {type:'url', value:item.image_url || ''});
    const saveBtn = el('button', {onclick: async ()=> {
      await api('/api/override', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ key: item.url, headline: headline.value, url: url.value, image_url: img.value })
      });
      alert('Saved override. Re-run curation.py to publish.');
    }}, ['Save']);
    const removeBtn = el('button', {onclick: async ()=> {
      await api('/api/override/delete', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ key: item.url })
      });
      alert('Removed override (if existed). Re-run curation.py.');
    }}, ['Remove Override']);

    tr.appendChild(el('td', {}, [headline]));
    tr.appendChild(el('td', {}, [url]));
    tr.appendChild(el('td', {}, [img]));
    tr.appendChild(el('td', {}, [el('div', {className:'row-controls'}, [saveBtn, removeBtn])]));
    tb.appendChild(tr);
  });
}

function renderBanned(list) {
  const ul = document.getElementById('banned-list'); ul.innerHTML = '';
  list.forEach(dom => {
    const li = el('li', {}, [
      el('span', {className:'mono'}, [dom]),
      el('span', {}, [' ']),
      el('button', {onclick: async ()=>{
        await api('/api/remove-domain', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ domain: dom })
        });
        loadState();
      }}, ['Remove'])
    ]);
    ul.appendChild(li);
  });
}

function renderFeeds(list) {
  const ul = document.getElementById('feeds-list'); ul.innerHTML = '';
  list.forEach(u => {
    const li = el('li', {}, [
      el('a', {href:u, target:'_blank'}, [u]),
      el('span', {}, [' ']),
      el('button', {onclick: async ()=>{
        await api('/api/remove-feed', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ feed_url: u })
        });
        loadState();
      }}, ['Remove'])
    ]);
    ul.appendChild(li);
  });
}

loadState().catch(err => {
  console.error(err);
  alert('Failed to load state. Make sure curated_items.json exists (run curation.py once).');
});
</script>
</body>
</html>
