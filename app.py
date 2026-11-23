import os
import time
import random
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ==============================================================================
# SQLITE PERSISTENT DATABASE LAYER
# ==============================================================================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clinic.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes persistent tables for students, active triage queues, and history."""
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Students Table (Permanent Accounts)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            srcode TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    # 2. Clinical History Table (Doctor Notes)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clinical_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            srcode TEXT NOT NULL,
            note TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (srcode) REFERENCES students (srcode)
        )
    ''')

    # 3. Active Queue Table (Persists Active Waiting Patients)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_queue (
            srcode TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            urgency TEXT NOT NULL,
            symptoms TEXT NOT NULL,
            severity INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
    ''')

    # 4. Seed Demo Student if not exists
    cursor.execute("SELECT srcode FROM students WHERE srcode = '24-09303'")
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO students (srcode, name, age, gender, password, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('24-09303', 'Juan P. Dela Cruz', 20, 'Male', 'student123', '2026-01-15 08:30'))

    conn.commit()
    conn.close()

# Initialize DB on launch
init_db()

# Staff Credentials
STAFF_CREDENTIALS = {
    "ADMIN": {
        "password": "batstateu411",
        "name": "Dr. A. Castillo, MD",
        "role": "admin"
    }
}

# ==============================================================================
# DATA STRUCTURE 1: BINARY SEARCH TREE (BST) FOR STUDENT DIRECTORY
# ==============================================================================
class BSTNode:
    def __init__(self, data):
        self.srcode = data['srcode']
        self.data = data
        self.left = None
        self.right = None

class BST:
    def __init__(self):
        self.root = None

    def insert(self, data):
        new_node = BSTNode(data)
        if not self.root:
            self.root = new_node
            return True
        current = self.root
        while True:
            if data['srcode'] < current.srcode:
                if not current.left:
                    current.left = new_node
                    return True
                current = current.left
            elif data['srcode'] > current.srcode:
                if not current.right:
                    current.right = new_node
                    return True
                current = current.right
            else:
                current.data = data  # Update existing
                return False

    def search(self, srcode):
        current = self.root
        while current:
            if srcode == current.srcode:
                return current.data
            elif srcode < current.srcode:
                current = current.left
            else:
                current = current.right
        return None

    def inorder(self):
        result = []
        def _inorder(node):
            if node:
                _inorder(node.left)
                result.append(node.data)
                _inorder(node.right)
        _inorder(self.root)
        return result

student_directory = BST()

def sync_bst_from_db():
    """Hydrates the in-memory Binary Search Tree from the persistent SQLite database."""
    global student_directory
    student_directory = BST()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students")
    rows = cursor.fetchall()
    for r in rows:
        cursor.execute("SELECT note, timestamp FROM clinical_notes WHERE srcode = ? ORDER BY id ASC", (r['srcode'],))
        history_rows = cursor.fetchall()
        history = [{'note': h['note'], 'timestamp': h['timestamp']} for h in history_rows]

        # Check if currently has active symptoms in queue
        cursor.execute("SELECT symptoms FROM active_queue WHERE srcode = ?", (r['srcode'],))
        active_q = cursor.fetchone()
        current_symp = active_q['symptoms'] if active_q else ''

        student_data = {
            'srcode': r['srcode'],
            'name': r['name'],
            'age': r['age'],
            'gender': r['gender'],
            'password': r['password'],
            'created_at': r['created_at'],
            'history': history,
            'current_symptoms': current_symp
        }
        student_directory.insert(student_data)
    conn.close()

# Perform initial sync
sync_bst_from_db()

# ==============================================================================
# DATA STRUCTURE 2: MAX-HEAP FOR EMERGENCY QUEUE
# ==============================================================================
class MaxHeap:
    def __init__(self):
        self.heap = []

    def insert(self, patient):
        self.heap.append(patient)
        self._sift_up(len(self.heap) - 1)

    def extract_max(self):
        if not self.heap:
            return None
        if len(self.heap) == 1:
            return self.heap.pop()
        root = self.heap[0]
        self.heap[0] = self.heap.pop()
        self._sift_down(0)
        return root

    def _sift_up(self, idx):
        parent = (idx - 1) // 2
        while idx > 0 and self.heap[idx]['severity'] > self.heap[parent]['severity']:
            self.heap[idx], self.heap[parent] = self.heap[parent], self.heap[idx]
            idx = parent
            parent = (idx - 1) // 2

    def _sift_down(self, idx):
        size = len(self.heap)
        while True:
            left = 2 * idx + 1
            right = 2 * idx + 2
            largest = idx
            if left < size and self.heap[left]['severity'] > self.heap[largest]['severity']:
                largest = left
            if right < size and self.heap[right]['severity'] > self.heap[largest]['severity']:
                largest = right
            if largest != idx:
                self.heap[idx], self.heap[largest] = self.heap[largest], self.heap[idx]
                idx = largest
            else:
                break

    def to_list(self):
        return sorted(self.heap, key=lambda p: -p['severity'])

    def contains(self, srcode):
        return any(p['srcode'] == srcode for p in self.heap)

    def remove(self, srcode):
        for i, p in enumerate(self.heap):
            if p['srcode'] == srcode:
                last = self.heap.pop()
                if i < len(self.heap):
                    self.heap[i] = last
                    self._sift_down(i)
                    self._sift_up(i)
                return p
        return None

# ==============================================================================
# DATA STRUCTURE 3: FIFO QUEUE FOR ROUTINE CLINIC CASES
# ==============================================================================
class FIFOQueue:
    def __init__(self):
        self.queue = []

    def enqueue(self, patient):
        self.queue.append(patient)

    def dequeue(self):
        if not self.queue:
            return None
        return self.queue.pop(0)

    def to_list(self):
        return list(self.queue)

    def contains(self, srcode):
        return any(p['srcode'] == srcode for p in self.queue)

    def remove(self, srcode):
        for i, p in enumerate(self.queue):
            if p['srcode'] == srcode:
                return self.queue.pop(i)
        return None

emergency_heap = MaxHeap()
routine_queue = FIFOQueue()

def sync_queues_from_db():
    """Syncs the in-memory Max-Heap and FIFO Queue from the database."""
    global emergency_heap, routine_queue
    emergency_heap = MaxHeap()
    routine_queue = FIFOQueue()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_queue ORDER BY created_at ASC")
    rows = cursor.fetchall()
    for r in rows:
        p_data = {
            'srcode': r['srcode'],
            'name': r['name'],
            'urgency': r['urgency'],
            'symptoms': r['symptoms'],
            'severity': r['severity'],
            'created_at': r['created_at']
        }
        if r['urgency'] == 'emergency':
            emergency_heap.insert(p_data)
        else:
            routine_queue.enqueue(p_data)
    conn.close()

sync_queues_from_db()

# Clinical Triage Severity Keyword Scorer
def calculate_severity(symptoms, urgency):
    s = symptoms.lower()
    score = 2
    if urgency == 'emergency':
        score = 6
    high_critical = ['chest pain', 'unconscious', 'breathing', 'seizure', 'kidney failure', 'stroke', 'cardiac', 'bleed', 'fracture', 'poison']
    medium_critical = ['severe', 'fainting', 'high fever', 'asthma', 'head trauma', 'vomiting blood', 'palpitations']
    for kw in high_critical:
        if kw in s:
            score += 3
    for kw in medium_critical:
        if kw in s:
            score += 2
    return min(max(score, 1), 10)

def mask_srcode(srcode):
    """Privacy masking for public calling board (e.g. 24-09303 -> 24-***03)"""
    if len(srcode) >= 8:
        return srcode[:3] + "***" + srcode[-2:]
    return srcode

# ==============================================================================
# FLASK WEB & API ROUTES
# ==============================================================================
@app.route('/')
def index():
    return render_template('index.html')

# 1. Student Registration
@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    srcode = data.get('srcode', '').strip()
    name = data.get('name', '').strip()
    age = data.get('age')
    gender = data.get('gender', 'Other').strip()
    password = data.get('password', '').strip()

    if not srcode or not name or not password or not age:
        return jsonify({'success': False, 'message': 'All registration fields are required.'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT srcode FROM students WHERE srcode = ?", (srcode,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': f'Student record with SR-Code {srcode} already exists.'}), 400

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    cursor.execute('''
        INSERT INTO students (srcode, name, age, gender, password, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (srcode, name, int(age), gender, password, created_at))
    conn.commit()
    conn.close()

    # Insert into BST
    student_record = {
        'srcode': srcode,
        'name': name,
        'age': int(age),
        'gender': gender,
        'password': password,
        'created_at': created_at,
        'history': [],
        'current_symptoms': ''
    }
    student_directory.insert(student_record)

    return jsonify({
        'success': True,
        'message': 'Account created successfully and saved permanently.',
        'user': {
            'role': 'student',
            'srcode': srcode,
            'name': name
        }
    })

# 2. Login Endpoint
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    user_id = data.get('id', '').strip()
    password = data.get('password', '').strip()

    # Check Staff Login
    if user_id.upper() in STAFF_CREDENTIALS:
        staff_info = STAFF_CREDENTIALS[user_id.upper()]
        if staff_info['password'] == password:
            return jsonify({
                'success': True,
                'user': {
                    'role': 'admin',
                    'srcode': user_id.upper(),
                    'name': staff_info['name']
                }
            })
        return jsonify({'success': False, 'message': 'Invalid staff credentials.'}), 401

    # Check Student Login: First search in BST
    student = student_directory.search(user_id)
    if not student:
        # Fallback check against persistent SQLite database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE srcode = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            sync_bst_from_db()
            student = student_directory.search(user_id)

    if student and student['password'] == password:
        return jsonify({
            'success': True,
            'user': {
                'role': 'student',
                'srcode': student['srcode'],
                'name': student['name']
            }
        })

    return jsonify({'success': False, 'message': 'Invalid SR-Code or password.'}), 401

# 3. Join Triage Queue
@app.route('/api/patient/join_queue', methods=['POST'])
def api_join_queue():
    data = request.get_json() or {}
    srcode = data.get('srcode', '').strip()
    symptoms = data.get('symptoms', '').strip()
    urgency = data.get('urgency', 'routine').strip().lower()

    if not srcode or not symptoms:
        return jsonify({'success': False, 'message': 'Symptoms are required for medical check-in.'}), 400

    # Check if student exists
    student = student_directory.search(srcode)
    if not student:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE srcode = ?", (srcode,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify({'success': False, 'message': 'Student record not found. Please register first.'}), 404
        sync_bst_from_db()
        student = student_directory.search(srcode)

    # Check if already waiting in persistent queue
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT srcode FROM active_queue WHERE srcode = ?", (srcode,))
    if cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'You are already waiting in the queue.'}), 400

    severity = calculate_severity(symptoms, urgency)
    created_at = time.time()

    cursor.execute('''
        INSERT INTO active_queue (srcode, name, urgency, symptoms, severity, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (srcode, student['name'], urgency, symptoms, severity, created_at))
    conn.commit()
    conn.close()

    patient_entry = {
        'srcode': srcode,
        'name': student['name'],
        'urgency': urgency,
        'symptoms': symptoms,
        'severity': severity,
        'created_at': created_at
    }

    if urgency == 'emergency':
        emergency_heap.insert(patient_entry)
    else:
        routine_queue.enqueue(patient_entry)

    student['current_symptoms'] = symptoms
    return jsonify({'success': True, 'message': 'Checked into clinic triage queue successfully.'})

# 4. Fetch All Data (Queues and Directory)
@app.route('/api/admin/all_data', methods=['GET'])
def api_all_data():
    raw_emergency = emergency_heap.to_list()
    raw_routine = routine_queue.to_list()
    all_students = student_directory.inorder()

    # Mask public queue data for board view
    public_emergency = [{'srcode': mask_srcode(p['srcode']), 'severity': p['severity']} for p in raw_emergency]
    public_routine = [{'srcode': mask_srcode(p['srcode']), 'severity': p['severity']} for p in raw_routine]

    return jsonify({
        'emergency_queue': raw_emergency,
        'routine_queue': raw_routine,
        'public_emergency': public_emergency,
        'public_routine': public_routine,
        'all_patients': all_students
    })

# 5. Staff: Call Next Patient
@app.route('/api/admin/call_next', methods=['POST'])
def api_call_next():
    data = request.get_json() or {}
    queue_type = data.get('queue_type', 'emergency')

    patient = None
    if queue_type == 'emergency':
        patient = emergency_heap.extract_max()
    else:
        patient = routine_queue.dequeue()

    if not patient:
        return jsonify({'success': False, 'message': f'No active patients in {queue_type.upper()} queue.'})

    # Remove from persistent database queue
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_queue WHERE srcode = ?", (patient['srcode'],))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"Now Calling: {patient['name']} ({patient['srcode']})",
        'patient': patient
    })

# 6. Staff: Add Medical Assessment Note
@app.route('/api/admin/add_comment', methods=['POST'])
def api_add_comment():
    data = request.get_json() or {}
    srcode = data.get('srcode', '').strip()
    comment = data.get('comment', '').strip()

    if not srcode or not comment:
        return jsonify({'success': False, 'message': 'SR-Code and diagnosis comment are required.'}), 400

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Save to SQLite
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO clinical_notes (srcode, note, timestamp)
        VALUES (?, ?, ?)
    ''', (srcode, comment, timestamp))
    conn.commit()
    conn.close()

    # Update in BST
    student = student_directory.search(srcode)
    if student:
        student.setdefault('history', []).append({'note': comment, 'timestamp': timestamp})

    return jsonify({'success': True, 'message': 'Clinical assessment saved successfully.'})

# 7. Search Benchmark (Linear vs Binary Search)
@app.route('/api/benchmark', methods=['GET'])
def api_benchmark():
    dataset_sizes = [100, 1000, 10000, 100000]
    results = []

    for n in dataset_sizes:
        data = sorted([f"24-{i:05d}" for i in range(n)])
        target = data[-1]

        # Linear Search O(N)
        t0 = time.perf_counter()
        found_lin = False
        for item in data:
            if item == target:
                found_lin = True
                break
        linear_ms = (time.perf_counter() - t0) * 1000.0

        # Binary Search O(log N)
        t1 = time.perf_counter()
        low = 0
        high = len(data) - 1
        found_bin = False
        while low <= high:
            mid = (low + high) // 2
            if data[mid] == target:
                found_bin = True
                break
            elif data[mid] < target:
                low = mid + 1
            else:
                high = mid - 1
        binary_ms = (time.perf_counter() - t1) * 1000.0

        results.append({
            'N': n,
            'linear_time_ms': round(linear_ms, 4),
            'binary_time_ms': round(binary_ms, 4)
        })

    return jsonify({'success': True, 'results': results})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
