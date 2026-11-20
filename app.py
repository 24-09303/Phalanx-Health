import os
import time
import random
import threading
from collections import deque
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "phalanx-health-cpe411-secret-key")

PH_TIME = timezone(timedelta(hours=8))
lock = threading.Lock()

def now_str():
    return datetime.now(PH_TIME).strftime("%b %d, %Y %I:%M %p")

# =====================================================================
# DSA 1: MAX-HEAP (Emergency Priority Triage)
# =====================================================================
class MaxHeap:
    def __init__(self):
        self.heap = []
        self._counter = 0

    def _key(self, item):
        return (item["severity"], -item["order"])

    def push(self, item):
        self._counter += 1
        item["order"] = self._counter
        self.heap.append(item)
        self._sift_up(len(self.heap) - 1)

    def pop(self):
        if not self.heap:
            return None
        top = self.heap[0]
        last = self.heap.pop()
        if self.heap:
            self.heap[0] = last
            self._sift_down(0)
        return top

    def _sift_up(self, i):
        while i > 0:
            parent = (i - 1) // 2
            if self._key(self.heap[i]) > self._key(self.heap[parent]):
                self.heap[i], self.heap[parent] = self.heap[parent], self.heap[i]
                i = parent
            else:
                break

    def _sift_down(self, i):
        n = len(self.heap)
        while True:
            largest = i
            left, right = 2 * i + 1, 2 * i + 2
            if left < n and self._key(self.heap[left]) > self._key(self.heap[largest]):
                largest = left
            if right < n and self._key(self.heap[right]) > self._key(self.heap[largest]):
                largest = right
            if largest == i:
                break
            self.heap[i], self.heap[largest] = self.heap[largest], self.heap[i]
            i = largest

    def contains(self, srcode):
        return any(p["srcode"] == srcode for p in self.heap)

    def sorted_view(self):
        return sorted(self.heap, key=self._key, reverse=True)

    def __len__(self):
        return len(self.heap)

# =====================================================================
# DSA 2: FIFO QUEUE (Routine Consultation Queue)
# =====================================================================
class PatientQueue:
    def __init__(self):
        self.items = deque()

    def enqueue(self, item):
        self.items.append(item)

    def dequeue(self):
        return self.items.popleft() if self.items else None

    def contains(self, srcode):
        return any(p["srcode"] == srcode for p in self.items)

    def to_list(self):
        return list(self.items)

    def __len__(self):
        return len(self.items)

# =====================================================================
# DSA 3: BINARY SEARCH TREE (Student Directory - O(log N) Search)
# =====================================================================
class BSTNode:
    def __init__(self, key, data):
        self.key = key
        self.data = data
        self.left = None
        self.right = None

class PatientBST:
    def __init__(self):
        self.root = None
        self.size = 0

    def insert(self, key, data):
        new_node = BSTNode(key, data)
        if self.root is None:
            self.root = new_node
            self.size += 1
            return True
        current = self.root
        while True:
            if key == current.key:
                return False
            if key < current.key:
                if current.left is None:
                    current.left = new_node
                    break
                current = current.left
            else:
                if current.right is None:
                    current.right = new_node
                    break
                current = current.right
        self.size += 1
        return True

    def search(self, key):
        current = self.root
        while current:
            if key == current.key:
                return current.data
            current = current.left if key < current.key else current.right
        return None

    def inorder(self):
        result, stack, current = [], [], self.root
        while stack or current:
            while current:
                stack.append(current)
                current = current.left
            current = stack.pop()
            result.append(current.data)
            current = current.right
        return result

# =====================================================================
# INITIAL DATA STORES
# =====================================================================
STAFF = {
    "ADMIN": {
        "srcode": "ADMIN",
        "name": "Clinic Administrator",
        "role": "admin",
        "password_hash": generate_password_hash("batstateu411")
    }
}

student_directory = PatientBST()
emergency_heap = MaxHeap()
routine_queue = PatientQueue()
treated_history = []

# Preload Demo Student
student_directory.insert("24-09303", {
    "srcode": "24-09303",
    "name": "Juan P. Dela Cruz",
    "age": 20,
    "gender": "Male",
    "department": "BS CpE",
    "year_level": "4th Year",
    "role": "student",
    "password_hash": generate_password_hash("student123"),
    "visits": []
})

CRITICAL_KEYWORDS = ["chest pain", "breathing", "unconscious", "fainted", "seizure", "bleeding", "severe", "fracture"]

def compute_severity(symptoms):
    s = symptoms.lower()
    score = 5
    hits = sum(1 for k in CRITICAL_KEYWORDS if k in s)
    score += min(hits * 3, 5)
    return min(max(score, 1), 10)

def mask_srcode(code):
    if not code or len(code) < 4:
        return "***"
    return code[:3] + "***" + code[-2:]

# =====================================================================
# ROUTES
# =====================================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode") or data.get("sr_code", "")).strip().upper()
    name = str(data.get("name") or data.get("fullname", "")).strip()
    age = data.get("age", 20)
    gender = str(data.get("gender", "Male")).strip()
    password = str(data.get("password", "")).strip()

    if not srcode or not name or not password:
        return jsonify({"error": "Please fill in all required fields."}), 400
    if srcode in STAFF:
        return jsonify({"error": "That ID is reserved for Staff."}), 400

    with lock:
        success = student_directory.insert(srcode, {
            "srcode": srcode,
            "name": name,
            "age": age,
            "gender": gender,
            "department": "CpE",
            "year_level": "Undergrad",
            "role": "student",
            "password_hash": generate_password_hash(password),
            "visits": []
        })

    if not success:
        return jsonify({"error": "SR-Code is already registered. Please Sign In."}), 400
    return jsonify({"message": "Account created successfully."})

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode") or data.get("sr_code", "")).strip().upper()
    password = str(data.get("password", "")).strip()

    if not srcode or not password:
        return jsonify({"error": "Please provide both ID and Password."}), 400

    user = STAFF.get(srcode)
    if user is None:
        with lock:
            user = student_directory.search(srcode)

    if user is None:
        return jsonify({"error": "Account not found. Please register first."}), 401
    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Incorrect password."}), 401

    session["srcode"] = user["srcode"]
    session["role"] = user["role"]

    return jsonify({
        "user": {
            "srcode": user["srcode"],
            "name": user["name"],
            "role": user["role"]
        }
    })

@app.route("/api/patient/join_queue", methods=["POST"])
def join_queue():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode") or session.get("srcode", "")).strip().upper()
    symptoms = str(data.get("symptoms", "")).strip()
    urgency = str(data.get("urgency", "routine")).strip().lower()

    if not srcode:
        return jsonify({"error": "Session expired. Please log in again."}), 401
    if not symptoms:
        return jsonify({"error": "Please enter your symptoms."}), 400

    with lock:
        patient = student_directory.search(srcode)
        if not patient:
            return jsonify({"error": "Student record not found."}), 404
        if emergency_heap.contains(srcode) or routine_queue.contains(srcode):
            return jsonify({"error": "You are already waiting in the queue."}), 400

        timestamp = now_str()
        entry = {
            "srcode": srcode,
            "name": patient["name"],
            "symptoms": symptoms,
            "time": timestamp
        }

        if urgency == "emergency":
            entry["severity"] = compute_severity(symptoms)
            emergency_heap.push(entry)
        else:
            entry["severity"] = None
            routine_queue.enqueue(entry)

        patient["visits"].append({
            "symptoms": symptoms,
            "urgency": urgency,
            "date": timestamp,
            "comment": "",
            "status": "waiting"
        })

    return jsonify({"message": "Successfully joined the queue."})

@app.route("/api/admin/all_data")
def all_data():
    is_staff = session.get("role") == "admin"
    with lock:
        all_patients = [
            {k: v for k, v in p.items() if k != "password_hash"}
            for p in student_directory.inorder()
        ]
        if is_staff:
            return jsonify({
                "patients": all_patients,
                "emergency_queue": emergency_heap.sorted_view(),
                "routine_queue": routine_queue.to_list(),
                "treated_history": treated_history
            })
        else:
            # Masked view for public/student screens
            return jsonify({
                "patients": [],
                "emergency_queue": [{"srcode": mask_srcode(e["srcode"])} for e in emergency_heap.sorted_view()],
                "routine_queue": [{"srcode": mask_srcode(e["srcode"])} for e in routine_queue.to_list()],
                "treated_history": []
            })

@app.route("/api/admin/call_next", methods=["POST"])
def call_next():
    if session.get("role") != "admin":
        return jsonify({"error": "Staff access required."}), 403

    data = request.get_json(silent=True) or {}
    queue_type = str(data.get("type", "")).strip().lower()

    with lock:
        if queue_type == "emergency":
            entry = emergency_heap.pop()
        elif queue_type == "routine":
            entry = routine_queue.dequeue()
        else:
            return jsonify({"error": "Invalid queue selection."}), 400

        if not entry:
            return jsonify({"error": f"The {queue_type} queue is currently empty."}), 400

        patient = student_directory.search(entry["srcode"])
        if patient:
            for v in reversed(patient["visits"]):
                if v.get("status") == "waiting":
                    v["status"] = "treated"
                    break

        treated_history.insert(0, {
            "srcode": entry["srcode"],
            "name": entry["name"],
            "queue": queue_type,
            "timestamp": now_str()
        })

    return jsonify({"patient": entry})

@app.route("/api/admin/add_comment", methods=["POST"])
def add_comment():
    if session.get("role") != "admin":
        return jsonify({"error": "Staff access required."}), 403

    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode", "")).strip().upper()
    comment = str(data.get("comment", "")).strip()

    with lock:
        patient = student_directory.search(srcode)
        if not patient:
            return jsonify({"error": "Student record not found."}), 404

        if patient["visits"]:
            patient["visits"][-1]["comment"] = comment
        else:
            patient["visits"].append({
                "symptoms": "Walk-in checkup",
                "urgency": "routine",
                "date": now_str(),
                "comment": comment,
                "status": "treated"
            })

    return jsonify({"message": "Assessment recorded."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
