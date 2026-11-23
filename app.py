import os
import time
import sqlite3
import random
import heapq
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import io

app = Flask(__name__)

# --- DATABASE SETUP ---
DB_PATH = 'clinic.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS students (
            srcode TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            password TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS clinical_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            srcode TEXT,
            note TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (srcode) REFERENCES students (srcode)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS active_queue (
            srcode TEXT PRIMARY KEY,
            name TEXT,
            urgency TEXT,
            symptoms TEXT,
            severity INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()

# --- DATA STRUCTURES ---
class BSTNode:
    def __init__(self, student_data):
        self.srcode = student_data['srcode']
        self.data = student_data
        self.left = None
        self.right = None

class StudentBST:
    def __init__(self):
        self.root = None
    
    def insert(self, student_data):
        if not self.root:
            self.root = BSTNode(student_data)
        else:
            self._insert(self.root, student_data)

    def _insert(self, node, student_data):
        if student_data['srcode'] < node.srcode:
            if node.left: self._insert(node.left, student_data)
            else: node.left = BSTNode(student_data)
        elif student_data['srcode'] > node.srcode:
            if node.right: self._insert(node.right, student_data)
            else: node.right = BSTNode(student_data)
        else:
            node.data = student_data

    def search(self, srcode):
        return self._search(self.root, srcode)

    def _search(self, node, srcode):
        if not node or node.srcode == srcode: return node
        if srcode < node.srcode: return self._search(node.left, srcode)
        return self._search(node.right, srcode)

# In-Memory State
student_directory = StudentBST()
emergency_heap = [] # Max-Heap: (-severity, timestamp, data)
routine_queue = []   # FIFO: (timestamp, data)

def sync_from_db():
    global emergency_heap, routine_queue
    init_db()
    with get_db() as conn:
        # Load BST
        rows = conn.execute("SELECT * FROM students").fetchall()
        for r in rows:
            s_data = dict(r)
            notes = conn.execute("SELECT note, timestamp FROM clinical_notes WHERE srcode=? ORDER BY timestamp DESC", (r['srcode'],)).fetchall()
            s_data['history'] = [dict(n) for n in notes]
            student_directory.insert(s_data)
        
        # Load Queues
        q_rows = conn.execute("SELECT * FROM active_queue ORDER BY created_at ASC").fetchall()
        emergency_heap = []
        routine_queue = []
        for q in q_rows:
            p = dict(q)
            ts = datetime.strptime(p['created_at'], '%Y-%m-%d %H:%M:%S').timestamp()
            if p['urgency'] == 'Emergency':
                heapq.heappush(emergency_heap, (-p['severity'], ts, p))
            else:
                routine_queue.append(p)

# Global Staff Credentials
STAFF_CREDENTIALS = {"id": "ADMIN", "pass": "batstateu411"}

# --- UTILS ---
def calculate_severity(symptoms):
    score = 1
    symptoms = symptoms.lower()
    critical = ["chest pain", "unconscious", "breathing", "fracture", "bleeding", "seizure"]
    moderate = ["fever", "vomiting", "abdominal", "dizzy", "headache"]
    for s in critical: 
        if s in symptoms: score = max(score, 9)
    for s in moderate:
        if s in symptoms: score = max(score, 5)
    return score + random.randint(0, 1)

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/spartan.png')
def get_logo():
    # Attempt to serve actual file, fallback to SVG-in-PNG logic if missing
    try:
        return send_file('static/spartan.png', mimetype='image/png')
    except:
        svg = '''<svg width="200" height="200" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" fill="white"/>
            <path d="M50 15 L70 35 L70 55 L50 75 L30 55 L30 35 Z" fill="#800000"/>
            <path d="M45 10 Q50 0 55 10 L55 30 L45 30 Z" fill="#FFC72C"/>
            <text x="50" y="90" font-family="Arial" font-weight="bold" font-size="12" fill="#800000" text-anchor="middle">SPARTAN</text>
        </svg>'''
        return svg, 200, {'Content-Type': 'image/svg+xml'}

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.json
    srcode, name, pwd = data.get('srcode'), data.get('name'), data.get('password')
    if not srcode or not name or not pwd: return jsonify({"error": "Missing fields"}), 400
    
    hashed = generate_password_hash(pwd)
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO students (srcode, name, age, gender, password) VALUES (?,?,?,?,?)",
                         (srcode, name, data.get('age', 18), data.get('gender', 'N/A'), hashed))
            conn.commit()
        sync_from_db()
        return jsonify({"message": "Success"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "SR-Code already exists"}), 400

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    uid, pwd = data.get('id'), data.get('password')
    if uid == STAFF_CREDENTIALS['id'] and pwd == STAFF_CREDENTIALS['pass']:
        return jsonify({"role": "staff", "token": "STAFF_SECRET_2024"})
    
    node = student_directory.search(uid)
    if node and check_password_hash(node.data['password'], pwd):
        return jsonify({"role": "student", "user": {"srcode": node.srcode, "name": node.data['name']}})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/patient/join_queue', methods=['POST'])
def api_join_queue():
    data = request.json
    srcode, urgency, symptoms = data.get('srcode'), data.get('urgency'), data.get('symptoms')
    name = data.get('name')
    severity = calculate_severity(symptoms) if urgency == "Emergency" else 0
    
    with get_db() as conn:
        conn.execute("REPLACE INTO active_queue (srcode, name, urgency, symptoms, severity) VALUES (?,?,?,?,?)",
                     (srcode, name, urgency, symptoms, severity))
        conn.commit()
    sync_from_db()
    return jsonify({"message": "Joined Queue"})

@app.route('/api/board', methods=['GET'])
def api_board():
    # Public board with masked IDs
    emergency = sorted([{"name": x[2]['name'], "srcode": f"{x[2]['srcode'][:3]}***{x[2]['srcode'][-2:]}"} for x in emergency_heap])
    routine = [{"name": x['name'], "srcode": f"{x['srcode'][:3]}***{x['srcode'][-2:]}"} for x in routine_queue]
    return jsonify({"emergency": emergency, "routine": routine})

@app.route('/api/admin/all_data', methods=['GET'])
def api_admin_data():
    if request.headers.get('X-Staff-Token') != "STAFF_SECRET_2024": return jsonify({"error": "Auth"}), 403
    
    e_list = [x[2] for x in sorted(emergency_heap)]
    r_list = list(routine_queue)
    
    all_students = []
    def traverse(node):
        if node:
            traverse(node.left)
            all_students.append(node.data)
            traverse(node.right)
    traverse(student_directory.root)
    
    return jsonify({"emergency": e_list, "routine": r_list, "directory": all_students})

@app.route('/api/admin/call_next', methods=['POST'])
def api_call_next():
    if request.headers.get('X-Staff-Token') != "STAFF_SECRET_2024": return jsonify({"error": "Auth"}), 403
    q_type = request.json.get('type')
    
    target_srcode = None
    if q_type == "emergency" and emergency_heap:
        target_srcode = heapq.heappop(emergency_heap)[2]['srcode']
    elif q_type == "routine" and routine_queue:
        target_srcode = routine_queue.pop(0)['srcode']
    
    if target_srcode:
        with get_db() as conn:
            conn.execute("DELETE FROM active_queue WHERE srcode=?", (target_srcode,))
            conn.commit()
        return jsonify({"message": "Called", "srcode": target_srcode})
    return jsonify({"error": "Queue empty"}), 400

@app.route('/api/admin/add_comment', methods=['POST'])
def api_add_comment():
    if request.headers.get('X-Staff-Token') != "STAFF_SECRET_2024": return jsonify({"error": "Auth"}), 403
    data = request.json
    with get_db() as conn:
        conn.execute("INSERT INTO clinical_notes (srcode, note) VALUES (?,?)", (data['srcode'], data['note']))
        conn.commit()
    sync_from_db()
    return jsonify({"message": "Note Added"})

if __name__ == '__main__':
    sync_from_db()
    app.run(debug=True)
