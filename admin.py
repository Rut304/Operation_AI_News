#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, render_template
import os, json, tldextract

OVERRIDES_FILE = 'overrides.json'
BANNED_DOMAINS_FILE = 'banned_domains.json'
CUSTOM_FEEDS_FILE = 'custom_feeds.json'
CURATED_DATA_FILE = 'curated_items.json'
ADMIN_CONFIG_FILE = 'admin_config.json'  # NEW

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')

app = Flask(__name__, template_folder='templates', static_folder='static')

DEFAULT_CONFIG = {"disable_mirror": False, "disable_overrides": False, "disable_custom_feeds": False}

def ensure_files():
    if not os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, 'w', encoding='utf-8') as f: json.dump({'overrides': {}}, f)
    if not os.path.exists(BANNED_DOMAINS_FILE):
        with open(BANNED_DOMAINS_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
    if not os.path.exists(CUSTOM_FEEDS_FILE):
        with open(CUSTOM_FEEDS_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
    if not os.path.exists(CURATED_DATA_FILE):
        with open(CURATED_DATA_FILE, 'w', encoding='utf-8') as f: json.dump({'items': []}, f)
    if not os.path.exists(ADMIN_CONFIG_FILE):  # NEW
        with open(ADMIN_CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(DEFAULT_CONFIG, f)

def auth_ok(req):
    return req.headers.get('X-Admin-Key') == ADMIN_PASSWORD

def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/state', methods=['GET'])
def api_state():
    ensure_files()
    items     = load_json(CURATED_DATA_FILE, {'items': []}).get('items', [])
    overrides = load_json(OVERRIDES_FILE, {'overrides': {}}).get('overrides', {})
    banned    = load_json(BANNED_DOMAINS_FILE, [])
    feeds     = load_json(CUSTOM_FEEDS_FILE, [])
    config    = load_json(ADMIN_CONFIG_FILE, DEFAULT_CONFIG)  # NEW
    return jsonify({'items': items, 'overrides': overrides, 'banned_domains': banned, 'custom_feeds': feeds, 'config': config})

@app.route('/api/config', methods=['POST'])  # NEW
def api_config():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True) or {}
    config = load_json(ADMIN_CONFIG_FILE, DEFAULT_CONFIG)
    for k in ('disable_mirror','disable_overrides','disable_custom_feeds'):
        if k in payload:
            config[k] = bool(payload[k])
    save_json(ADMIN_CONFIG_FILE, config)
    return jsonify({'ok': True, 'config': config})

@app.route('/api/override', methods=['POST'])
def api_override():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True)
    key = (payload or {}).get('key')
    if not key: return jsonify({'error':'missing key'}), 400
    ov = {k:v for k,v in payload.items() if k in ('headline','url','image_url') and v is not None}
    data = load_json(OVERRIDES_FILE, {'overrides': {}})
    data.setdefault('overrides', {})
    existing = data['overrides'].get(key, {})
    existing.update(ov)
    data['overrides'][key] = existing
    save_json(OVERRIDES_FILE, data)
    return jsonify({'ok': True, 'override': data['overrides'][key]})

@app.route('/api/override/delete', methods=['POST'])
def api_override_delete():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True)
    key = (payload or {}).get('key')
    if not key: return jsonify({'error':'missing key'}), 400
    data = load_json(OVERRIDES_FILE, {'overrides': {}})
    if key in data.get('overrides', {}):
        del data['overrides'][key]
        save_json(OVERRIDES_FILE, data)
    return jsonify({'ok': True})

@app.route('/api/ban-domain', methods=['POST'])
def api_ban_domain():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True)
    dom = (payload or {}).get('domain', '').strip()
    if not dom: return jsonify({'error':'missing domain'}), 400
    d = tldextract.extract(dom).domain.lower()
    banned = load_json(BANNED_DOMAINS_FILE, [])
    if d and d not in banned:
        banned.append(d)
        save_json(BANNED_DOMAINS_FILE, banned)
    return jsonify({'ok': True, 'banned_domains': banned})

@app.route('/api/remove-domain', methods=['POST'])
def api_remove_domain():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True)
    dom = (payload or {}).get('domain', '').strip()
    d = tldextract.extract(dom).domain.lower()
    banned = load_json(BANNED_DOMAINS_FILE, [])
    banned = [x for x in banned if x != d]
    save_json(BANNED_DOMAINS_FILE, banned)
    return jsonify({'ok': True, 'banned_domains': banned})

@app.route('/api/add-feed', methods=['POST'])
def api_add_feed():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True)
    url = (payload or {}).get('feed_url', '').strip()
    if not url: return jsonify({'error':'missing feed_url'}), 400
    feeds = load_json(CUSTOM_FEEDS_FILE, [])
    if url not in feeds:
        feeds.append(url)
        save_json(CUSTOM_FEEDS_FILE, feeds)
    return jsonify({'ok': True, 'custom_feeds': feeds})

@app.route('/api/remove-feed', methods=['POST'])
def api_remove_feed():
    if not auth_ok(request): return jsonify({'error':'unauthorized'}), 401
    payload = request.get_json(force=True)
    url = (payload or {}).get('feed_url', '').strip()
    feeds = load_json(CUSTOM_FEEDS_FILE, [])
    feeds = [u for u in feeds if u != url]
    save_json(CUSTOM_FEEDS_FILE, feeds)
    return jsonify({'ok': True, 'custom_feeds': feeds})

if __name__ == '__main__':
    ensure_files()
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=True)
