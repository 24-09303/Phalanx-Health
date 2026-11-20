from datetime import datetime
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = 'batstateu_spartan_dsa_clinic_secret_2025'

# ==============================================================================
# DATA STRUCTURES (CPE 411 REQUIREMENTS)
# ==============================================================================

class MaxHeap:
    """Max-Heap Priority Queue for Emergency Triage cases O(log N)."""
    def __init__(self):
        self.heap = []

    def insert(self, patient):
        self.heap.append(patient)
        self._heapify_up(len(self.heap) - 1)

    def extract_max(self):
        if not self.heap:
            return None
        if len(self.heap) == 1:
            return self.heap.pop()
        root = self.heap[0]
        self.heap[0] = self.heap.pop()
        self._heapify_down(0)
        return root

    def _heapify_up(self, index):
        parent = (index - 1) // 2
        if index > 0 and self.heap[index]['severity'] > self.heap[parent]['severity']:
            self.heap[index], self.heap[parent] = self.heap[parent], self.heap[index]
            self._heapify_up(parent)

    def _heapify_down(self, index):
        largest = index
        left, right = 2 * index + 1, 2 * index + 2
        size = len(self.heap)

        if left < size and self.heap[left]['severity'] > self.heap[largest]['severity']:
            largest = left
        if right < size and self.heap[right]['severity'] > self.heap[largest]['severity']:
            largest = right
        if largest != index:
            self.heap[index], self.heap[largest] = self.heap[largest], self.heap[index]
            self._heapify_down(largest)

    def get_all(self):
        return sorted(self.heap, key=lambda x: x['severity'], reverse=True)

    def size(self):
        return len(self.heap)

    def has_active(self, sr_code):
        return any(p['sr_code'] == sr_code for p in self.heap)


class PatientQueue:
    """FIFO Queue for Routine Consultations O(1)."""
    def __init__(self):
        self.queue = []

    def enqueue(self, patient):
        self.queue.append(patient)

    def dequeue(self):
        return self.queue.pop(0) if self.queue else None

    def get_all(self):
        return list(self.queue)

    def size(self):
        return len(self.queue)

    def has_active(self, sr_code):
        return any(p['sr_code'] == sr_code for p in self.queue)


class BSTNode:
    def __init__(self, record):
        self.record = record
        self.left = None
        self.right = None


class PatientBST:
    """Binary Search Tree for Fast O(log N) Student Directory Lookup."""
    def __init__(self):
        self.root = None

    def insert(self, record):
        new_node = BSTNode(record)
        if not self.root:
            self.root = new_node
            return True
        curr = self.root
        while True:
            if record['sr_code'] == curr.record['sr_code']:
                # Update existing record
                curr.record = record
                return True
            elif record['sr_code'] < curr.record['sr_code']:
                if curr.left is None:
                    curr.left = new_node
                    return True
                curr = curr.left
            else:
                if curr.right is None:
                    curr.right = new_node
                    return True
                curr = curr.right

    def search(self, sr_code):
        curr = self.root
        while curr:
            if sr_code == curr.record['sr_code']:
                return curr.record
            elif sr_code < curr.record['sr_code']:
                curr = curr.left
            else:
                curr = curr.right
        return None

    def get_inorder(self, node=None, result=None):
        if result is None:
            result = []
            node = self.root
        if node:
            self.get_inorder(node.left, result)
            result.append(node.record)
            self.get_inorder(node.right, result)
        return result


# ==============================================================================
# GLOBAL STORAGE & PRE-SEEDED ACCOUNTS
# ==============================================================================

triage_heap = MaxHeap()
routine_queue = PatientQueue()
patient_bst = PatientBST()
treatment_history = []

stats = {
    'total_registered': 0,
    'total_treated': 0,
    'emergencies_handled': 0,
    'routine_handled': 0
}

# User Account Database: { sr_code: { password, name, age, gender, role, history } }
users_db = {
    "ADMIN": {
        "sr_code": "ADMIN",
        "password": "batstateu411",
        "name": "Dr. Vicente Ramos (MD)",
        "role": "admin",
        "age": 45,
        "gender": "Male",
        "history": []
    },
    "24-09303": {
        "sr_code": "24-09303",
        "password": "student123",
        "name": "Maria Christine Santos",
        "role": "student",
        "age": 20,
        "gender": "Female",
        "history": [
            {
                "ticket": "R-100",
                "type": "Routine",
                "date": "2025-01-15",
                "symptoms": "Annual OJT Medical Clearance",
                "comments": ["Cleared for internship. BP 110/70. Fit to work."]
            }
        ]
    },
    "23-01824": {
        "sr_code": "23-01824",
        "password": "student123",
        "name": "Juan Dela Cruz",
        "role": "student",
        "age": 21,
        "gender": "Male",
        "history": []
    }
}

# Pre-populate directory with seed students
for user_key, u in users_db.items():
    if u['role'] == 'student':
        stats['total_registered'] += 1
        patient_bst.insert({
            'sr_code': u['sr_code'],
            'name': u['name'],
            'age': u['age'],
            'gender': u['gender'],
            'last_ticket': 'None',
            'status': 'Idle'
        })

# Add one initial emergency ticket into the Max-Heap for Maria Santos
seed_ticket = {
    "ticket": "E-101",
    "sr_code": "24-09303",
    "name": "Maria Christine Santos",
    "age": 20,
    "gender": "Female",
    "type": "Emergency",
    "severity": 9,
    "symptoms": "Severe acute abdominal spasms and nausea",
    "comments": ["Initial triage vitals: BP 130/90, Pulse 102 bpm. Administering antispasmodic."],
    "registered_at": "08:30 AM",
    "status": "Waiting"
}
triage_heap.insert(seed_ticket)
patient_bst.insert({
    'sr_code': "24-09303",
    'name': "Maria Christine Santos",
    'age': 20,
    'gender': "Female",
    'last_ticket': "E-101",
    'status': "Waiting (Emergency)"
})


def mask_sr_code(code):
    if '-' in code:
        parts = code.split('-')
        return f"{parts[0]}-*****"
    return code[:3] + "*****" if len(code) > 3 else "*****"


# ==============================================================================
# AUTHENTICATION ENDPOINTS
# ==============================================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.json or {}
    sr_code = data.get('sr_code', '').strip().upper()
    name = data.get('name', '').strip()
    password = data.get('password', '').strip()
    age = data.get('age', 20)
    gender = data.get('gender', 'Male')

    if not sr_code or not name or not password:
        return jsonify({'success': False, 'message': 'All fields are required!'}), 400

    if sr_code in users_db:
        return jsonify({'success': False, 'message': f'Account with SR-Code {sr_code} already exists!'}), 400

    # Create new student account
    users_db[sr_code] = {
        'sr_code': sr_code,
        'name': name,
        'password': password,
        'role': 'student',
        'age': int(age),
        'gender': gender,
        'history': []
    }

    # Register into BST Master Directory
    patient_bst.insert({
        'sr_code': sr_code,
        'name': name,
        'age': int(age),
        'gender': gender,
        'last_ticket': 'None',
        'status': 'Idle'
    })
    stats['total_registered'] += 1

    return jsonify({'success': True, 'message': 'Account registered successfully! You can now log in.'})


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.json or {}
    sr_code = data.get('sr_code', '').strip().upper()
    password = data.get('password', '').strip()

    user = users_db.get(sr_code)
    if user and user['password'] == password:
        session['sr_code'] = sr_code
        session['role'] = user['role']
        session['name'] = user['name']
        return jsonify({
            'success': True,
            'role': user['role'],
            'sr_code': sr_code,
            'name': user['name']
        })
    return jsonify({'success': False, 'message': 'Invalid SR-Code or Password!'}), 401


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/auth/session', methods=['GET'])
def auth_session():
    if 'sr_code' in session:
        return jsonify({
            'logged_in': True,
            'sr_code': session.get('sr_code'),
            'role': session.get('role'),
            'name': session.get('name')
        })
    return jsonify({'logged_in': False})


# ==============================================================================
# PATIENT / STUDENT PORTAL ENDPOINTS
# ==============================================================================

@app.route('/api/patient/my_portal', methods=['GET'])
def patient_my_portal():
    sr_code = session.get('sr_code')
    if not sr_code or session.get('role') != 'student':
        return jsonify({'error': 'Unauthorized'}), 401

    user = users_db.get(sr_code)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Search if student has an active ticket in queues
    active_ticket = None
    queue_pos = None

    # Check emergency heap
    heap_list = triage_heap.get_all()
    for idx, p in enumerate(heap_list):
        if p['sr_code'] == sr_code:
            active_ticket = p
            queue_pos = f"#{idx + 1} in Urgent Priority Triage (Max-Heap)"
            break

    # Check routine queue
    if not active_ticket:
        routine_list = routine_queue.get_all()
        for idx, p in enumerate(routine_list):
            if p['sr_code'] == sr_code:
                active_ticket = p
                queue_pos = f"#{idx + 1} in Routine Consultation Queue (FIFO)"
                break

    return jsonify({
        'user': {
            'sr_code': user['sr_code'],
            'name': user['name'],
            'age': user['age'],
            'gender': user['gender']
        },
        'active_ticket': active_ticket,
        'queue_pos': queue_pos,
        'history': user['history']
    })


@app.route('/api/patient/join_queue', methods=['POST'])
def patient_join_queue():
    sr_code = session.get('sr_code')
    if not sr_code or session.get('role') != 'student':
        return jsonify({'error': 'Unauthorized'}), 401

    if triage_heap.has_active(sr_code) or routine_queue.has_active(sr_code):
        return jsonify({'success': False, 'message': 'You already have an active ticket waiting in the queue!'}), 400

    user = users_db[sr_code]
    data = request.json or {}
    c_type = data.get('type', 'Routine')
    severity = int(data.get('severity', 3 if c_type == 'Routine' else 7))
    symptoms = data.get('symptoms', 'No symptoms specified').strip()

    ticket_prefix = 'E' if c_type == 'Emergency' else 'R'
    ticket_no = f"{ticket_prefix}-{stats['total_treated'] + triage_heap.size() + routine_queue.size() + 101}"

    ticket_obj = {
        'ticket': ticket_no,
        'sr_code': sr_code,
        'name': user['name'],
        'age': user['age'],
        'gender': user['gender'],
        'type': c_type,
        'severity': severity,
        'symptoms': symptoms,
        'comments': [],
        'registered_at': datetime.now().strftime('%I:%M %p'),
        'status': 'Waiting'
    }

    if c_type == 'Emergency':
        triage_heap.insert(ticket_obj)
    else:
        routine_queue.enqueue(ticket_obj)

    # Update BST Record status
    patient_bst.insert({
        'sr_code': sr_code,
        'name': user['name'],
        'age': user['age'],
        'gender': user['gender'],
        'last_ticket': ticket_no,
        'status': f"Waiting ({c_type})"
    })

    return jsonify({'success': True, 'ticket': ticket_obj})


@app.route('/api/public_queue', methods=['GET'])
def public_queue():
    """Confidential Display: Tickets & Masked SR-Codes ONLY (NO symptoms)."""
    emg = [{'ticket': p['ticket'], 'masked_sr': mask_sr_code(p['sr_code']), 'time': p['registered_at']} for p in triage_heap.get_all()]
    rtn = [{'ticket': p['ticket'], 'masked_sr': mask_sr_code(p['sr_code']), 'time': p['registered_at']} for p in routine_queue.get_all()]

    return jsonify({
        'stats': {
            'total_registered': stats['total_registered'],
            'emergency_count': triage_heap.size(),
            'routine_count': routine_queue.size(),
            'total_treated': stats['total_treated']
        },
        'emergency_list': emg,
        'routine_list': rtn
    })


# ==============================================================================
# CLINIC STAFF / ADMIN APIS
# ==============================================================================

def verify_admin():
    return session.get('role') == 'admin'


@app.route('/api/admin/all_data', methods=['GET'])
def admin_all_data():
    if not verify_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    return jsonify({
        'stats': {
            'total_registered': stats['total_registered'],
            'emergency_count': triage_heap.size(),
            'routine_count': routine_queue.size(),
            'total_treated': stats['total_treated']
        },
        'emergency_queue': triage_heap.get_all(),
        'routine_queue': routine_queue.get_all(),
        'all_records': patient_bst.get_inorder(),
        'history': treatment_history
    })


@app.route('/api/admin/call_next', methods=['POST'])
def admin_call_next():
    if not verify_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    q_type = data.get('type', 'emergency')

    patient = triage_heap.extract_max() if q_type == 'emergency' else routine_queue.dequeue()
    if not patient:
        return jsonify({'success': False, 'message': 'No patients in this queue!'}), 404

    patient['status'] = 'Treated'
    patient['treated_at'] = datetime.now().strftime('%I:%M %p')
    treatment_history.insert(0, patient)
    stats['total_treated'] += 1

    # Save to user's personal medical record
    sr = patient['sr_code']
    if sr in users_db:
        users_db[sr]['history'].insert(0, {
            'ticket': patient['ticket'],
            'type': patient['type'],
            'date': datetime.now().strftime('%Y-%m-%d %I:%M %p'),
            'symptoms': patient['symptoms'],
            'comments': list(patient['comments'])
        })

    # Update BST
    student_rec = patient_bst.search(sr)
    if student_rec:
        student_rec['status'] = 'Completed'

    return jsonify({'success': True, 'patient': patient})


@app.route('/api/admin/add_comment', methods=['POST'])
def admin_add_comment():
    if not verify_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    sr_code = data.get('sr_code', '').strip().upper()
    comment = data.get('comment', '').strip()

    if not sr_code or not comment:
        return jsonify({'success': False, 'message': 'Missing SR-Code or Comment'}), 400

    timestamp = datetime.now().strftime('%I:%M %p')
    note_text = f"[{timestamp}] Dr. Assessment: {comment}"

    # Search in active emergency heap
    for p in triage_heap.heap:
        if p['sr_code'] == sr_code:
            p['comments'].append(note_text)
            return jsonify({'success': True, 'comments': p['comments']})

    # Search in active routine queue
    for p in routine_queue.queue:
        if p['sr_code'] == sr_code:
            p['comments'].append(note_text)
            return jsonify({'success': True, 'comments': p['comments']})

    # Search in treatment history
    for p in treatment_history:
        if p['sr_code'] == sr_code:
            p['comments'].append(note_text)
            return jsonify({'success': True, 'comments': p['comments']})

    # Add to user database directly
    if sr_code in users_db and users_db[sr_code]['history']:
        users_db[sr_code]['history'][0]['comments'].append(note_text)
        return jsonify({'success': True, 'comments': users_db[sr_code]['history'][0]['comments']})

    return jsonify({'success': False, 'message': 'Patient active file not found.'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
