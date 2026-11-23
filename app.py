import os
import time
import secrets
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
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS students (
            srcode TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS clinical_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            srcode TEXT NOT NULL,
            note TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS active_queue (
            srcode TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            urgency TEXT NOT NULL,
            symptoms TEXT NOT NULL,
            severity INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
    ''')

    # Seed demo student
    cur.execute('''
        INSERT OR IGNORE INTO students (srcode, name, age, gender, password, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ('24-09303', 'Juan P. Dela Cruz', 20, 'Male', 'student123', '2026-01-15 08:30'))

    conn.commit()
    conn.close()


init_db()

# Staff credentials
STAFF_CREDENTIALS = {
    "ADMIN": {
        "password": "batstateu411",
        "name": "Dr. A. Castillo, MD"
    }
}
STAFF_TOKENS = set()


def is_staff(req):
    return req.headers.get('X-Staff-Token', '') in STAFF_TOKENS


# ==============================================================================
# DATA STRUCTURE 1: BINARY SEARCH TREE (STUDENT DIRECTORY)
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
                current.data = data
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

        def _walk(node):
            if node:
                _walk(node.left)
                result.append(node.data)
                _walk(node.right)

        _walk(self.root)
        return result


# ==============================================================================
# DATA STRUCTURE 2: MAX-HEAP (EMERGENCY QUEUE)
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
        while idx > 0:
            parent = (idx - 1) // 2
            if self.heap[idx]['severity'] > self.heap[parent]['severity']:
                self.heap[idx], self.heap[parent] = self.heap[parent], self.heap[idx]
                idx = parent
            else:
                break

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
            if largest == idx:
                break
            self.heap[idx], self.heap[largest] = self.heap[largest], self.heap[idx]
            idx = largest

    def to_list(self):
        return sorted(self.heap, key=lambda p: (-p['severity'], p['created_at']))


# ==============================================================================
# DATA STRUCTURE 3: FIFO QUEUE (ROUTINE CASES)
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


student_directory = BST()
emergency_heap = MaxHeap()
routine_queue = FIFOQueue()


def sync_bst_from_db():
    global student_directory
    new_tree = BST()

    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()
    notes = conn.execute("SELECT srcode, note, timestamp FROM clinical_notes ORDER BY id ASC").fetchall()
    queued = conn.execute("SELECT srcode, symptoms FROM active_queue").fetchall()
    conn.close()

    history_map = {}
    for n in notes:
        history_map.setdefault(n['srcode'], []).append({'note': n['note'], 'timestamp': n['timestamp']})
    symptom_map = {q['srcode']: q['symptoms'] for q in queued}

    for r in students:
        new_tree.insert({
            'srcode': r['srcode'],
            'name': r['name'],
            'age': r['age'],
            'gender': r['gender'],
            'password': r['password'],
            'created_at': r['created_at'],
            'history': history_map.get(r['srcode'], []),
            'current_symptoms': symptom_map.get(r['srcode'], '')
        })

    student_directory = new_tree


def sync_queues_from_db():
    global emergency_heap, routine_queue
    new_heap = MaxHeap()
    new_routine = FIFOQueue()

    conn = get_db()
    rows = conn.execute("SELECT * FROM active_queue ORDER BY created_at ASC").fetchall()
    conn.close()

    for r in rows:
        p = {
            'srcode': r['srcode'],
            'name': r['name'],
            'urgency': r['urgency'],
            'symptoms': r['symptoms'],
            'severity': r['severity'],
            'created_at': r['created_at']
        }
        if r['urgency'] == 'emergency':
            new_heap.insert(p)
        else:
            new_routine.enqueue(p)

    emergency_heap = new_heap
    routine_queue = new_routine


sync_bst_from_db()
sync_queues_from_db()


def calculate_severity(symptoms, urgency):
    s = symptoms.lower()
    score = 6 if urgency == 'emergency' else 2
    high_critical = ['chest pain', 'unconscious', 'breathing', 'seizure', 'kidney failure',
                     'stroke', 'cardiac', 'bleed', 'fracture', 'poison']
    medium_critical = ['severe', 'fainting', 'high fever', 'asthma', 'head trauma',
                       'vomiting blood', 'palpitations']
    for kw in high_critical:
        if kw in s:
            score += 3
    for kw in medium_critical:
        if kw in s:
            score += 2
    return min(max(score, 1), 10)


def mask_srcode(srcode):
    if len(srcode) >= 8:
        return srcode[:3] + "***" + srcode[-2:]
    return srcode[:2] + "***" if len(srcode) > 2 else "***"


def find_student(srcode):
    record = student_directory.search(srcode)
    if record:
        return record
    conn = get_db()
    row = conn.execute("SELECT srcode FROM students WHERE srcode = ?", (srcode,)).fetchone()
    conn.close()
    if row:
        sync_bst_from_db()
        return student_directory.search(srcode)
    return None


# ==============================================================================
# ROUTES
# ==============================================================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get('srcode', '')).strip()
    name = str(data.get('name', '')).strip()
    gender = str(data.get('gender', 'Other')).strip() or 'Other'
    password = str(data.get('password', '')).strip()

    try:
        age = int(data.get('age'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Age must be a valid number.'}), 400

    if not srcode or not name or not password:
        return jsonify({'success': False, 'message': 'All registration fields are required.'}), 400

    conn = get_db()
    existing = conn.execute("SELECT srcode FROM students WHERE srcode = ?", (srcode,))
    if existing.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': f'SR-Code {srcode} is already registered.'}), 400

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn.execute(
        "INSERT INTO students (srcode, name, age, gender, password, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (srcode, name, age, gender, password, created_at)
    )
    conn.commit()
    conn.close()

    sync_bst_from_db()

    return jsonify({
        'success': True,
        'message': 'Account created and saved permanently.',
        'user': {'role': 'student', 'srcode': srcode, 'name': name}
    })


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('id', '')).strip()
    password = str(data.get('password', '')).strip()

    if user_id.upper() in STAFF_CREDENTIALS:
        info = STAFF_CREDENTIALS[user_id.upper()]
        if info['password'] == password:
            token = secrets.token_hex(16)
            STAFF_TOKENS.add(token)
            return jsonify({
                'success': True,
                'user': {'role': 'admin', 'srcode': user_id.upper(), 'name': info['name'], 'token': token}
            })
        return jsonify({'success': False, 'message': 'Invalid staff credentials.'}), 401

    student = find_student(user_id)
    if student and student['password'] == password:
        return jsonify({
            'success': True,
            'user': {'role': 'student', 'srcode': student['srcode'], 'name': student['name']}
        })

    return jsonify({'success': False, 'message': 'Invalid SR-Code or password.'}), 401


@app.route('/api/patient/join_queue', methods=['POST'])
def api_join_queue():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get('srcode', '')).strip()
    symptoms = str(data.get('symptoms', '')).strip()
    urgency = str(data.get('urgency', 'routine')).strip().lower()
    if urgency not in ('routine', 'emergency'):
        urgency = 'routine'

    if not srcode or not symptoms:
        return jsonify({'success': False, 'message': 'Symptoms are required for check-in.'}), 400

    student = find_student(srcode)
    if not student:
        return jsonify({'success': False, 'message': 'Student record not found. Please sign out and re-register.'}), 404

    severity = calculate_severity(symptoms, urgency)
    created_at = time.time()

    conn = get_db()
    existing = conn.execute("SELECT srcode FROM active_queue WHERE srcode = ?", (srcode,)).fetchone()

    if existing:
        # If already in queue, update their entry so they aren't blocked
        conn.execute(
            "UPDATE active_queue SET urgency = ?, symptoms = ?, severity = ?, created_at = ? WHERE srcode = ?",
            (urgency, symptoms, severity, created_at, srcode)
        )
        msg = "Your symptoms and queue entry have been updated."
    else:
        conn.execute(
            "INSERT INTO active_queue (srcode, name, urgency, symptoms, severity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (srcode, student['name'], urgency, symptoms, severity, created_at)
        )
        msg = "You have successfully joined the medical triage queue."

    conn.commit()
    conn.close()

    # Immediately sync MaxHeap and FIFOQueue
    sync_queues_from_db()
    student['current_symptoms'] = symptoms

    return jsonify({'success': True, 'message': msg})


@app.route('/api/board', methods=['GET'])
def api_board():
    # Sync from DB so calling board is always fresh
    sync_queues_from_db()

    emergency = [
        {'srcode': mask_srcode(p['srcode']), 'position': i + 1}
        for i, p in enumerate(emergency_heap.to_list())
    ]
    routine = [
        {'srcode': mask_srcode(p['srcode']), 'position': i + 1}
        for i, p in enumerate(routine_queue.to_list())
    ]

    return jsonify({
        'emergency': emergency,
        'routine': routine,
        'emergency_queue': emergency,
        'routine_queue': routine
    })


@app.route('/api/admin/all_data', methods=['GET'])
def api_all_data():
    if not is_staff(request):
        return jsonify({'success': False, 'message': 'Staff authentication required.'}), 401

    sync_queues_from_db()
    sync_bst_from_db()

    emergency = emergency_heap.to_list()
    routine = routine_queue.to_list()
    patients = [{k: v for k, v in s.items() if k != 'password'} for s in student_directory.inorder()]

    return jsonify({
        'emergency_queue': emergency,
        'routine_queue': routine,
        'all_patients': patients
    })


@app.route('/api/admin/call_next', methods=['POST'])
def api_call_next():
    if not is_staff(request):
        return jsonify({'success': False, 'message': 'Staff authentication required.'}), 401

    data = request.get_json(silent=True) or {}
    queue_type = data.get('queue_type', 'emergency')

    sync_queues_from_db()

    if queue_type == 'emergency':
        patient = emergency_heap.extract_max()
    else:
        patient = routine_queue.dequeue()

    if not patient:
        return jsonify({'success': False, 'message': f'No active patients in the {queue_type} queue.'})

    conn = get_db()
    conn.execute("DELETE FROM active_queue WHERE srcode = ?", (patient['srcode'],))
    conn.commit()
    conn.close()

    sync_queues_from_db()

    return jsonify({
        'success': True,
        'message': f"Now calling {patient['name']} ({patient['srcode']}).",
        'patient': patient
    })


@app.route('/api/admin/add_comment', methods=['POST'])
def api_add_comment():
    if not is_staff(request):
        return jsonify({'success': False, 'message': 'Staff authentication required.'}), 401

    data = request.get_json(silent=True) or {}
    srcode = str(data.get('srcode', '')).strip()
    comment = str(data.get('comment', '')).strip()

    if not srcode or not comment:
        return jsonify({'success': False, 'message': 'SR-Code and assessment note are required.'}), 400

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = get_db()
    conn.execute(
        "INSERT INTO clinical_notes (srcode, note, timestamp) VALUES (?, ?, ?)",
        (srcode, comment, timestamp)
    )
    conn.commit()
    conn.close()

    student = student_directory.search(srcode)
    if student:
        student.setdefault('history', []).append({'note': comment, 'timestamp': timestamp})

    return jsonify({'success': True, 'message': 'Clinical assessment saved to student record.'})


@app.route('/api/benchmark', methods=['GET'])
def api_benchmark():
    dataset_sizes = [100, 1000, 10000, 100000]
    results = []

    for n in dataset_sizes:
        data = sorted(f"24-{i:05d}" for i in range(n))
        target = data[-1]

        t0 = time.perf_counter()
        for item in data:
            if item == target:
                break
        linear_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        low, high = 0, len(data) - 1
        while low <= high:
            mid = (low + high) // 2
            if data[mid] == target:
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
