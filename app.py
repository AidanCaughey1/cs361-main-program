from flask import (
    Flask, redirect, request, session, url_for,
    jsonify, render_template
)
import requests, os, urllib.parse, sqlite3


app = Flask(__name__)
app.secret_key = os.urandom(24)

CLIENT_ID     = '47bed45cb9644ea7a98c53f43808139b'
CLIENT_SECRET = '632bd18d36cf45cca39262f063aafaf2'
REDIRECT_URI  = 'http://127.0.0.1:5000/callback'
SCOPE         = 'user-read-recently-played user-read-private'
DB_PATH       = 'collections.db'

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
          CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            collection_name TEXT,
            song_name TEXT,
            artist_name TEXT
          )
        ''')
        cur.execute('''
          CREATE TABLE IF NOT EXISTS user_collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            collection_name TEXT
          )
        ''')
        conn.commit()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def login():
    params = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPE
    }
    return redirect('https://accounts.spotify.com/authorize?' + urllib.parse.urlencode(params))

@app.route('/callback')
def callback():
    code = request.args.get('code')
    resp = requests.post('https://accounts.spotify.com/api/token', data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    })
    token = resp.json()['access_token']
    session['access_token'] = token

    profile = requests.get('https://api.spotify.com/v1/me',
        headers={'Authorization': f'Bearer {token}'}
    ).json()
    session['user_id']  = profile['id']
    session['username'] = profile.get('display_name', profile['id'])
    return redirect(url_for('home'))

@app.route('/recently-played')
def recently_played():
    token = session.get('access_token'); user = session.get('user_id')
    if not token or not user:
        return redirect(url_for('home'))

    items = requests.get(
        'https://api.spotify.com/v1/me/player/recently-played',
        headers={'Authorization': f'Bearer {token}'}
    ).json().get('items', [])

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('SELECT collection_name FROM user_collections WHERE user_id=?', (user,))
        cols = [r[0] for r in cur.fetchall()]

    return render_template('recently_played.html', items=items, collections=cols)

@app.route('/search')
def search():
    q = request.args.get('q'); token = session.get('access_token'); user = session.get('user_id')
    if not (q and token and user):
        return redirect(url_for('home'))

    tracks = requests.get(
        'https://api.spotify.com/v1/search',
        headers={'Authorization': f'Bearer {token}'},
        params={'q': q, 'type': 'track', 'limit': 10}
    ).json().get('tracks', {}).get('items', [])

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('SELECT collection_name FROM user_collections WHERE user_id=?', (user,))
        cols = [r[0] for r in cur.fetchall()]

    return render_template('search.html', tracks=tracks, collections=cols, query=q)

@app.route('/add', methods=['POST'])
def add_to_collection():
    song, artist = request.form['song'], request.form['artist']
    col, user    = request.form['collection'], session.get('user_id')
    if not all([song, artist, col, user]):
        return jsonify(success=False, message='Missing info'), 400

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
          INSERT INTO collections
            (user_id, collection_name, song_name, artist_name)
          VALUES (?,?,?,?)''', (user, col, song, artist))
        conn.commit()

    return jsonify(success=True, message=f'Added "{song}" to {col}')

@app.route('/remove', methods=['POST'])
def remove_from_collection():
    song, artist = request.form['song'], request.form['artist']
    col, user    = request.form['collection'], session.get('user_id')
    if not all([song, artist, col, user]):
        return jsonify(success=False, message='Missing info'), 400

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
          DELETE FROM collections
          WHERE user_id=? AND collection_name=? AND song_name=? AND artist_name=?''',
          (user, col, song, artist))
        conn.commit()

    return jsonify(success=True, message=f'Removed "{song}" from {col}')

@app.route('/collections', methods=['GET','POST'])
def collections_view():
    user = session.get('user_id')
    if not user:
        return redirect(url_for('home'))

    if request.method == 'POST':
        nc = request.form['new_collection']
        if nc:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute('INSERT INTO user_collections (user_id,collection_name) VALUES (?,?)', (user, nc))
                conn.commit()
        return redirect(url_for('collections_view'))

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT collection_name FROM user_collections WHERE user_id=?', (user,))
        cols = [r[0] for r in cur.fetchall()]

    return render_template('collections.html', collections=cols)

@app.route('/collection/<collection_name>')
def view_collection(collection_name):
    user = session.get('user_id')
    if not user:
        return redirect(url_for('home'))

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
          SELECT song_name, artist_name FROM collections
          WHERE user_id=? AND collection_name=?''', (user, collection_name))
        songs = cur.fetchall()

    return render_template('collection.html', collection_name=collection_name, songs=songs)

@app.route('/delete_collection', methods=['POST'])
def delete_collection():
    user = session.get('user_id')
    col = request.form.get('collection')
    if not user or not col:
        return jsonify(success=False, message='Missing info'), 400

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        # Delete songs in the collection
        cur.execute('DELETE FROM collections WHERE user_id=? AND collection_name=?', (user, col))
        # Delete the collection itself
        cur.execute('DELETE FROM user_collections WHERE user_id=? AND collection_name=?', (user, col))
        conn.commit()

    return jsonify(success=True, message=f'Deleted collection "{col}"')


if __name__=='__main__':
    init_db()
    app.run(debug=True)
