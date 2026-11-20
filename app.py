import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = 'batstateu_spartan_medtriage_key_2025'

# ==============================================================================
# DATA STRUCTURES (CPE 411 REQUIREMENTS)
# ==============================================================================

class MaxHeap:
    """Max-Heap Priority Queue for Emergency Triage cases."""
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

    def remove_by_id(self, patient_id):
        for idx, p in enumerate(self.heap):
            if p['id'] == patient_id:
                removed = self.heap.pop(idx)
                # Rebuild heap structure
                temp = list(self.heap)
                self.heap = []
                for item in temp:
                    self.insert(item)
                return removed
        return None

    def size(self):
        return len(self.heap)


class PatientQueue:
    """FIFO Queue for Routine Non-Emergency Consultations."""
    def __init__(self):
        self.queue = []

    def enqueue(self, patient):
        self.queue.append(patient)

    def dequeue(self):
        return self.queue.pop(0) if self.queue else None

    def remove_by_id(self, patient_id):
        for idx, p in enumerate(self.queue):
            if p['id'] == patient_id:
                return self.queue.pop(idx)
        return None

    def get_all(self):
        return list(self.queue)

    def size(self):
        return len(self.queue)


class BSTNode:
    def __init__(self, patient):
        self.patient = patient
        self.left = None
        self.right = None


class PatientBST:
    """Binary Search Tree for fast O(log N) patient record lookup."""
    def __init__(self):
        self.root = None

    def insert(self, patient):
        new_node = BSTNode(patient)
        if not self.root:
            self.root = new_node
            return True
        curr = self.root
        while True:
            if patient['id'] == curr.patient['id']:
                return False  # Prevent Duplicate SR-Code
            elif patient['id'] < curr.patient['id']:
                if curr.left is None:
                    curr.left = new_node
                    return True
                curr = curr.left
            else:
                if curr.right is None:
                    curr.right = new_node
                    return True
                curr = curr.right

    def search(self, patient_id):
        curr = self.root
        while curr:
            if patient_id == curr.patient['id']:
                return curr.patient
            elif patient_id < curr.patient['id']:
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
            result.append(node.patient)
            self.get_inorder(node.right, result)
        return result


# ==============================================================================
# GLOBAL STATE & INITIAL SEED DATA
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

# Seed Accounts (Admins + Demo Students)
accounts = {
    "ADMIN": {
        "password": "batstateu411",
        "role": "admin",
        "name": "Head Clinic Physician"
    },
    "24-09303": {
        "password": "student123",
        "role": "patient",
        "name": "Maria Santos"
    }
}

# Pre-load initial patients
seed_patients = [
    {
        "id": "24-09303",
        "name": "Maria Santos",
        "age": 20,
        "gender": "Female",
        "type": "Emergency",
        "ticket": "E-101",
        "severity": 9,
        "symptoms": "Severe abdominal trauma and difficulty breathing",
        "comments": ["Admitted to Bed 1. Administered oxygen."],
        "registered_at": "08:15 AM",
        "status": "Waiting"
    },
    {
        "id": "23-01824",
        "name": "Juan Dela Cruz",
        "age": 21,
        "gender": "Male",
        "type": "Routine",
        "ticket": "R-201",
        "severity": 2,
        "symptoms": "Annual OJT medical clearance physical exam",
        "comments": [],
        "registered_at": "08:30 AM",
        "status": "Waiting"
    },
    {
        "id": "22-04512",
        "name": "Carlos Gomez",
        "age": 19,
        "gender": "Male",
        "type": "Emergency",
        "ticket": "E-102",
        "severity": 7,
        "symptoms": "Sprained ankle during varsity practice, intense swelling",
        "comments": ["Ice pack applied at triage entrance."],
        "registered_at": "08:45 AM",
        "status": "Waiting"
    }
]

for p in seed_patients:
    patient_bst.insert(p)
    stats['total_registered'] += 1
    if p['type'] == 'Emergency':
        triage_heap.insert(p)
    else:
        routine_queue.enqueue(p)


def mask_sr_code(code):
    """Masks SR-Code for student privacy (e.g. 24-09303 -> 24-*****)."""
    if '-' in code:
        parts = code.split('-')
        return f"{parts[0]}-*****"
    return code[:3] + "*****" if len(code) > 3 else "*****"


# ==============================================================================
# ROUTING & API ENDPOINTS
# ==============================================================================

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    sr_code = data.get('sr_code', '').strip().upper()
    password = data.get('password', '').strip()

    if sr_code in accounts and accounts[sr_code]['password'] == password:
        session['user_id'] = sr_code
        session['role'] = accounts[sr_code]['role']
        session['user_name'] = accounts[sr_code]['name']
        return jsonify({
            'success': True,
            'role': session['role'],
            'sr_code': sr_code,
            'name': session['user_name']
        })
    return jsonify({'success': False, 'message': 'Invalid SR-Code or Password!'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/session', methods=['GET'])
def get_session():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'role': session.get('role'),
            'sr_code': session.get('user_id'),
            'name': session.get('user_name')
        })
    return jsonify({'logged_in': False})


@app.route('/api/register_student', methods=['POST'])
def register_student():
    """Allows a student to self-register for clinic triage."""
    data = request.json or {}
    sr_code = data.get('id', '').strip().upper()
    name = data.get('name', '').strip()
    password = data.get('password', '').strip() or 'student123'
    c_type = data.get('type', 'Routine')
    severity = int(data.get('severity', 3 if c_type == 'Routine' else 7))
    symptoms = data.get('symptoms', 'None provided')
    age = data.get('age', 20)
    gender = data.get('gender', 'Male')

    if not sr_code or not name:
        return jsonify({'success': False, 'message': 'SR-Code and Full Name are required.'}), 400

    # Generate Queue Ticket Number
    ticket = f"{'E' if c_type == 'Emergency' else 'R'}-{stats['total_registered'] + 101}"

    patient = {
        'id': sr_code,
        'name': name,
        'age': age,
        'gender': gender,
        'type': c_type,
        'ticket': ticket,
        'severity': severity,
        'symptoms': symptoms,
        'comments': [],
        'registered_at': datetime.now().strftime('%I:%M %p'),
        'status': 'Waiting'
    }

    if not patient_bst.insert(patient):
        return jsonify({'success': False, 'message': f'SR-Code {sr_code} is already registered in the system!'}), 400

    # Save to user login registry
    accounts[sr_code] = {
        'password': password,
        'role': 'patient',
        'name': name
    }

    stats['total_registered'] += 1

    if c_type == 'Emergency':
        triage_heap.insert(patient)
    else:
        routine_queue.enqueue(patient)

    return jsonify({'success': True, 'ticket': ticket, 'patient': patient})


@app.route('/api/public_queue', methods=['GET'])
def public_queue():
    """Confidential Queue Board: Returns only tickets and masked codes. NO SYMPTOMS."""
    emergencies = []
    for p in triage_heap.get_all():
        emergencies.append({
            'ticket': p['ticket'],
            'masked_id': mask_sr_code(p['id']),
            'type': p['type'],
            'registered_at': p['registered_at'],
            'status': p['status']
        })

    routines = []
    for p in routine_queue.get_all():
        routines.append({
            'ticket': p['ticket'],
            'masked_id': mask_sr_code(p['id']),
            'type': p['type'],
            'registered_at': p['registered_at'],
            'status': p['status']
        })

    return jsonify({
        'stats': {
            'registered': stats['total_registered'],
            'emergency_count': len(emergencies),
            'routine_count': len(routines),
            'treated_count': stats['total_treated']
        },
        'emergencies': emergencies,
        'routines': routines
    })


@app.route('/api/my_status', methods=['GET'])
def patient_my_status():
    """Returns confidential details strictly for the currently logged-in student."""
    sr_code = session.get('user_id')
    if not sr_code or session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    patient = patient_bst.search(sr_code)
    if not patient:
        return jsonify({'success': False, 'message': 'Record not found.'})

    # Determine place in queue
    pos = "Completed"
    if patient['type'] == 'Emergency':
        heap_list = triage_heap.get_all()
        for idx, p in enumerate(heap_list):
            if p['id'] == sr_code:
                pos = f"#{idx + 1} in Urgent Priority Triage"
                break
    else:
        q_list = routine_queue.get_all()
        for idx, p in enumerate(q_list):
            if p['id'] == sr_code:
                pos = f"#{idx + 1} in General Consultation Line"
                break

    return jsonify({'success': True, 'patient': patient, 'queue_position': pos})


# ==============================================================================
# CLINIC STAFF / ADMIN ONLY APIS
# ==============================================================================

def verify_admin():
    return session.get('role') == 'admin'


@app.route('/api/admin/all_data', methods=['GET'])
def admin_all_data():
    if not verify_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    return jsonify({
        'stats': {
            'registered': stats['total_registered'],
            'emergency_count': triage_heap.size(),
            'routine_count': routine_queue.size(),
            'treated_count': stats['total_treated']
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
        return jsonify({'success': False, 'message': 'Queue is empty!'}), 404

    patient['status'] = 'Treated'
    patient['treated_at'] = datetime.now().strftime('%I:%M %p')
    treatment_history.insert(0, patient)
    stats['total_treated'] += 1

    return jsonify({'success': True, 'patient': patient})


@app.route('/api/admin/add_comment', methods=['POST'])
def admin_add_comment():
    if not verify_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    sr_code = data.get('id', '').strip()
    comment = data.get('comment', '').strip()

    if not sr_code or not comment:
        return jsonify({'success': False, 'message': 'Missing SR-Code or Comment'}), 400

    patient = patient_bst.search(sr_code)
    if not patient:
        return jsonify({'success': False, 'message': 'Student record not found in BST'}), 404

    timestamp = datetime.now().strftime('%I:%M %p')
    note_entry = f"[{timestamp}] Dr. Assessment: {comment}"
    patient['comments'].append(note_entry)

    return jsonify({'success': True, 'comments': patient['comments']})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
