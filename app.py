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

PH_TIME = timezone(timedelta(hours=8))   # Philippine Standard Time
lock = threading.Lock()


def now_str():
    return datetime.now(PH_TIME).strftime("%b %d, %Y %I:%M %p")


# =====================================================================
# DSA 1: MAX-HEAP  (Emergency Triage - highest severity is served first)
# =====================================================================
class MaxHeap:
    def __init__(self):
        self.heap = []
        self._counter = 0

    def _key(self, item):
        # Higher severity first; if tied, earlier arrival first
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
# DSA 2: FIFO QUEUE  (Routine Patients - first come, first served)
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
# DSA 3: BINARY SEARCH TREE  (Student Directory - O(log N) lookup)
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
                return False  # duplicate SR-Code
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
        """Iterative in-order traversal -> patients sorted by SR-Code."""
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
# ILO2: LINEAR SEARCH vs BINARY SEARCH (backend benchmark for report)
# =====================================================================
def linear_search(arr, target):
    for i, value in enumerate(arr):
        if value == target:
            return i
    return -1


def binary_search(arr, target):
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1


def run_benchmark(sizes=(100, 1000, 10000, 100000), trials=50):
    results = []
    for n in sizes:
        data = list(range(0, n * 2, 2))          # sorted dataset
        targets = random.sample(data, min(trials, n))

        start = time.perf_counter()
        for t in targets:
            linear_search(data, t)
        linear_time = (time.perf_counter() - start) / len(targets)

        start = time.perf_counter()
        for t in targets:
            binary_search(data, t)
        binary_time = (time.perf_counter() - start) / len(targets)

        results.append({
            "n": n,
            "linear_avg_microseconds": round(linear_time * 1_000_000, 3),
            "binary_avg_microseconds": round(binary_time * 1_000_000, 3),
            "speedup": round(linear_time / binary_time, 2) if binary_time > 0 else None,
            "linear_complexity": "O(n)",
            "binary_complexity": "O(log n)",
        })
    return results


# =====================================================================
# DATA STORES
# =====================================================================
STAFF = {
    "ADMIN": {
        "srcode": "ADMIN",
        "name": "Clinic Administrator",
        "role": "admin",
        "password_hash": generate_password_hash("batstateu411"),
    }
}

student_directory = PatientBST()
emergency_heap = MaxHeap()
routine_queue = PatientQueue()
treated_history = []

# Demo student account
student_directory.insert("24-09303", {
    "srcode": "24-09303",
    "name": "Demo Student",
    "department": "BS CpE",
    "year_level": "2nd Year",
    "role": "student",
    "password_hash": generate_password_hash("student123"),
    "visits": [],
})


# =====================================================================
# HELPERS
# =====================================================================
CRITICAL_KEYWORDS = [
    "chest pain", "can't breathe", "cannot breathe", "difficulty breathing",
    "shortness of breath", "unconscious", "fainted", "seizure", "bleeding",
    "allergic", "anaphylaxis", "poison", "head injury", "fracture",
]
MODERATE_KEYWORDS = [
    "fever", "vomit", "dizzy", "dizziness", "sprain", "burn", "asthma",
    "migraine", "high blood", "diarrhea", "wound", "cut",
]


def compute_severity(symptoms):
    """Severity score 1-10 used as the Max-Heap priority key."""
    s = symptoms.lower()
    score = 5
    critical_hits = sum(1 for k in CRITICAL_KEYWORDS if k in s)
    moderate_hits = sum(1 for k in MODERATE_KEYWORDS if k in s)
    score += min(critical_hits * 4, 5)
    score += min(moderate_hits, 2)
    return max(1, min(score, 10))


def mask_srcode(code):
    if not code or len(code) < 4:
        return "***"
    return code[:3] + "***" + code[-2:]


def public_patient(p):
    """Patient record without the password hash."""
    return {k: v for k, v in p.items() if k != "password_hash"}


def queue_entry_view(e):
    return {
        "srcode": e["srcode"],
        "name": e["name"],
        "symptoms": e["symptoms"],
        "severity": e.get("severity"),
        "time": e["time"],
    }


def is_admin():
    return session.get("role") == "admin"


def error(message, status=400):
    return jsonify({"error": message}), status


# =====================================================================
# ROUTES
# =====================================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode", "")).strip().upper()
    name = str(data.get("name", "")).strip()
    department = str(data.get("department", "")).strip()
    year_level = str(data.get("year_level", "")).strip()
    password = str(data.get("password", "")).strip()

    if not all([srcode, name, department, year_level, password]):
        return error("Please fill in all fields.")
    if srcode in STAFF:
        return error("That ID is reserved.")
    if len(password) < 4:
        return error("Password must be at least 4 characters.")

    with lock:
        created = student_directory.insert(srcode, {
            "srcode": srcode,
            "name": name,
            "department": department,
            "year_level": year_level,
            "role": "student",
            "password_hash": generate_password_hash(password),
            "visits": [],
        })
    if not created:
        return error("This SR-Code is already registered. Please sign in.")
    return jsonify({"message": "Account created successfully."})


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode", "")).strip().upper()
    password = str(data.get("password", "")).strip()

    if not srcode or not password:
        return error("Please enter your SR-Code / Staff ID and password.")

    user = STAFF.get(srcode)
    if user is None:
        with lock:
            user = student_directory.search(srcode)   # BST lookup

    if user is None:
        return error("Account not found. Please register first.", 401)
    if not check_password_hash(user["password_hash"], password):
        return error("Incorrect password.", 401)

    session["srcode"] = user["srcode"]
    session["role"] = user["role"]

    return jsonify({"user": {
        "srcode": user["srcode"],
        "name": user["name"],
        "role": user["role"],
    }})


@app.route("/api/patient/join_queue", methods=["POST"])
def join_queue():
    srcode = session.get("srcode")
    if not srcode or session.get("role") != "student":
        return error("Session expired. Please sign in again.", 401)

    data = request.get_json(silent=True) or {}
    symptoms = str(data.get("symptoms", "")).strip()
    urgency = str(data.get("urgency", "routine")).strip().lower()

    if not symptoms:
        return error("Please describe your symptoms.")

    with lock:
        patient = student_directory.search(srcode)
        if patient is None:
            return error("Account not found. Please register again.", 404)
        if emergency_heap.contains(srcode) or routine_queue.contains(srcode):
            return error("You are already in the queue.")

        timestamp = now_str()
        entry = {
            "srcode": srcode,
            "name": patient["name"],
            "symptoms": symptoms,
            "time": timestamp,
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
            "status": "waiting",
        })

    return jsonify({"message": "Added to queue."})


@app.route("/api/admin/all_data")
def all_data():
    with lock:
        if is_admin():
            return jsonify({
                "patients": [public_patient(p) for p in student_directory.inorder()],
                "emergency_queue": [queue_entry_view(e) for e in emergency_heap.sorted_view()],
                "routine_queue": [queue_entry_view(e) for e in routine_queue.to_list()],
                "treated_history": treated_history,
            })

        # Students / public board: masked SR-Codes only, no names or symptoms
        return jsonify({
            "patients": [],
            "emergency_queue": [{"srcode": mask_srcode(e["srcode"])} for e in emergency_heap.sorted_view()],
            "routine_queue": [{"srcode": mask_srcode(e["srcode"])} for e in routine_queue.to_list()],
            "treated_history": [],
        })


@app.route("/api/admin/call_next", methods=["POST"])
def call_next():
    if not is_admin():
        return error("Staff access only.", 403)

    data = request.get_json(silent=True) or {}
    queue_type = str(data.get("type", "")).strip().lower()

    with lock:
        if queue_type == "emergency":
            entry = emergency_heap.pop()
        elif queue_type == "routine":
            entry = routine_queue.dequeue()
        else:
            return error("Invalid queue type.")

        if entry is None:
            return error(f"The {queue_type} queue is empty.")

        patient = student_directory.search(entry["srcode"])
        if patient:
            for visit in reversed(patient["visits"]):
                if visit.get("status") == "waiting":
                    visit["status"] = "treated"
                    break

        treated_history.insert(0, {
            "srcode": entry["srcode"],
            "name": entry["name"],
            "queue": queue_type,
            "timestamp": now_str(),
        })

    return jsonify({"patient": {"srcode": entry["srcode"], "name": entry["name"]}})


@app.route("/api/admin/add_comment", methods=["POST"])
def add_comment():
    if not is_admin():
        return error("Staff access only.", 403)

    data = request.get_json(silent=True) or {}
    srcode = str(data.get("srcode", "")).strip().upper()
    comment = str(data.get("comment", "")).strip()

    if not srcode or not comment:
        return error("Missing student or comment.")

    with lock:
        patient = student_directory.search(srcode)
        if patient is None:
            return error("Student not found.", 404)

        if patient["visits"]:
            latest = patient["visits"][-1]
            latest["comment"] = (latest["comment"] + " | " + comment) if latest["comment"] else comment
        else:
            patient["visits"].append({
                "symptoms": "Walk-in consultation",
                "urgency": "routine",
                "date": now_str(),
                "comment": comment,
                "status": "treated",
            })

    return jsonify({"message": "Assessment saved."})


@app.route("/api/benchmark")
def benchmark():
    """Linear vs Binary Search comparison (ILO2) - used for the technical report."""
    return jsonify({"results": run_benchmark()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
