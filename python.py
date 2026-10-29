"""스쿨쉐어 서버 (Flask)

기능별로 txt 파일에 저장합니다. (이 파일과 같은 폴더에 자동 생성)
  1.txt  회원(users)
  2.txt  게시판(posts)
  3.txt  반톡(cm)
  4.txt  1:1 채팅(dms)
  5.txt  조별과제(groups)
  6.txt  학생자치 논제(topics)
"""
import json
import os
import re
import secrets
import threading
import time

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 요청 최대 8MB

lock = threading.RLock()

FILES = {
    "users": "1.txt",
    "posts": "2.txt",
    "cm": "3.txt",
    "dms": "4.txt",
    "groups": "5.txt",
    "topics": "6.txt",
}

CODE = "123456"  # 데모용 고정 인증번호
DATAURL = re.compile(r"^data:[\w.+/-]{1,100};base64,[A-Za-z0-9+/=]*$")


# ---------- 저장 / 불러오기 ----------
def seed():
    """처음 실행할 때 넣는 데모 데이터 (프로토타입과 동일)"""
    ck = "한빛고등학교|2|3"
    return {
        "users": [
            {"id": 1, "role": "teacher", "school": "한빛고등학교", "dept": "교무부", "grade": "2", "cls": "3", "name": "김선생", "council": False, "demo": True},
            {"id": 2, "role": "student", "school": "한빛고등학교", "dept": "", "grade": "2", "cls": "3", "name": "이회장", "council": True, "demo": True},
            {"id": 3, "role": "student", "school": "한빛고등학교", "dept": "", "grade": "2", "cls": "3", "name": "박학생", "council": False, "demo": True},
            {"id": 4, "role": "student", "school": "한빛고등학교", "dept": "", "grade": "2", "cls": "3", "name": "최학생", "council": False, "demo": True},
        ],
        "posts": [{"id": 1, "uid": 3, "text": "수학 3단원 정리 노트 공유해요 📚", "img": None, "file": None, "t": "10:20"}],
        "cm": [{"id": 1, "uid": 2, "text": "내일 체육복 챙기세요!", "t": "09:00", "ck": ck}],
        "dms": {},
        "groups": [{"id": 1, "name": "과학 조별과제 1조", "tid": 1, "members": [2, 3], "msgs": [{"uid": 3, "text": "자료조사 나눌까요?", "t": "11:00"}]}],
        "topics": [{"id": 1, "uid": 2, "period": "주간", "text": "야간자율학습 시간 조정 의견 모으기", "yes": [3], "no": []}],
    }


def load_all():
    defaults = seed()
    data = {}
    for key, name in FILES.items():
        path = os.path.join(BASE_DIR, name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data[key] = json.load(f)
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        data[key] = defaults[key]
        write_file(key, data[key])
    return data


def write_file(key, value):
    path = os.path.join(BASE_DIR, FILES[key])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
    os.replace(tmp, path)


data = load_all()
sessions = {}  # {토큰: 회원 id}  (서버를 끄면 로그인도 풀림)
version = 1    # 데이터가 바뀔 때마다 +1 (화면이 바뀐 때만 새로 받게 함)


def commit(*keys):
    global version
    for k in keys:
        write_file(k, data[k])
    version += 1


# ---------- 공통 도구 ----------
class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def route(path, auth=True):
    def deco(fn):
        @app.route(path, methods=["POST"], endpoint=fn.__name__)
        def wrapper():
            body = request.get_json(silent=True) or {}
            with lock:
                me = None
                if auth:
                    uid = sessions.get(str(body.get("token", "")))
                    me = next((u for u in data["users"] if u["id"] == uid), None)
                    if not me:
                        return jsonify(ok=False, error="로그인이 필요해요"), 401
                try:
                    return jsonify(fn(me, body))
                except ApiError as e:
                    return jsonify(ok=False, error=str(e)), e.code
        return wrapper
    return deco


def txt(v, n):
    return str(v or "").strip()[:n]


def now():
    return time.strftime("%H:%M")


def new_id(items):
    return max([x["id"] for x in items], default=0) + 1


def new_session(uid):
    token = secrets.token_hex(16)
    sessions[token] = uid
    return token


def user_by_id(uid):
    return next((u for u in data["users"] if u["id"] == uid), None)


def same_school(me, uid):
    u = user_by_id(uid)
    return bool(u) and u["school"] == me["school"]


def class_key(u):
    if u.get("grade") and u.get("cls"):
        return f'{u["school"]}|{u["grade"]}|{u["cls"]}'
    return None


def is_teacher(u):
    return u["role"] == "teacher"


def check_attachment(value, image=False):
    if not isinstance(value, str) or not DATAURL.match(value):
        raise ApiError("첨부 파일 형식이 올바르지 않아요")
    if image and not value.startswith("data:image/"):
        raise ApiError("이미지 형식이 올바르지 않아요")
    if len(value) > 4_500_000:
        raise ApiError("파일은 3MB 이하만 가능해요")
    return value


# ---------- 화면 ----------
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


# ---------- 1. 회원 ----------
@route("/api/accounts", auth=False)
def accounts(_, body):
    return {"ok": True, "users": [u for u in data["users"] if u.get("demo")]}


@route("/api/demo_login", auth=False)
def demo_login(_, body):
    u = user_by_id(body.get("id"))
    if not u or not u.get("demo"):
        raise ApiError("데모 계정이 아니에요", 404)
    return {"ok": True, "token": new_session(u["id"])}


@route("/api/login", auth=False)
def login(_, body):
    school, name = txt(body.get("school"), 40), txt(body.get("name"), 20)
    u = next((x for x in data["users"] if x["school"] == school and x["name"] == name), None)
    if not u:
        raise ApiError("학교와 이름이 일치하는 계정이 없어요", 404)
    return {"ok": True, "token": new_session(u["id"])}


@route("/api/signup", auth=False)
def signup(_, body):
    role = body.get("role")
    if role not in ("student", "teacher"):
        raise ApiError("역할을 선택하세요")
    school, name = txt(body.get("school"), 40), txt(body.get("name"), 20)
    grade, cls, dept = txt(body.get("grade"), 3), txt(body.get("cls"), 3), txt(body.get("dept"), 30)
    if not school or not name or (role == "student" and (not grade or not cls)):
        raise ApiError("필수 항목을 입력하세요")
    if str(body.get("code", "")) != CODE:
        raise ApiError("인증번호가 틀렸어요")
    if any(u["school"] == school and u["name"] == name for u in data["users"]):
        raise ApiError("같은 학교에 같은 이름의 계정이 이미 있어요", 409)
    user = {"id": new_id(data["users"]), "role": role, "school": school, "dept": dept,
            "grade": grade, "cls": cls, "name": name, "council": False, "demo": False}
    data["users"].append(user)
    commit("users")
    return {"ok": True, "token": new_session(user["id"])}


@route("/api/state")
def state(me, body):
    if body.get("v") == version:
        return {"ok": True, "same": True}
    school = me["school"]
    users = [u for u in data["users"] if u["school"] == school]
    ids = {u["id"] for u in users}
    ck = class_key(me)
    return {
        "ok": True, "v": version, "me": me, "users": users,
        "posts": [p for p in data["posts"] if p["uid"] in ids],
        "cm": [m for m in data["cm"] if ck and m["ck"] == ck],
        "dms": {k: v for k, v in data["dms"].items() if str(me["id"]) in k.split("-")},
        "groups": [g for g in data["groups"] if g["tid"] == me["id"] or me["id"] in g["members"]],
        "topics": [t for t in data["topics"] if t["uid"] in ids],
    }


# ---------- 2. 게시판 ----------
@route("/api/post")
def post_add(me, body):
    text = txt(body.get("text"), 2000)
    img, file = body.get("img"), body.get("file")
    if img:
        img = check_attachment(img, image=True)
    if file:
        if not isinstance(file, dict):
            raise ApiError("첨부 파일 형식이 올바르지 않아요")
        file = {"name": txt(file.get("name"), 100) or "file", "data": check_attachment(file.get("data"))}
    if not text and not img and not file:
        raise ApiError("내용을 입력하세요")
    data["posts"].append({"id": new_id(data["posts"]), "uid": me["id"], "text": text,
                          "img": img or None, "file": file or None, "t": now()})
    commit("posts")
    return {"ok": True}


@route("/api/post/delete")
def post_delete(me, body):
    p = next((x for x in data["posts"] if x["id"] == body.get("id")), None)
    if not p or not same_school(me, p["uid"]):
        raise ApiError("글을 찾을 수 없어요", 404)
    if not (p["uid"] == me["id"] or is_teacher(me) or me["council"]):
        raise ApiError("삭제 권한이 없어요", 403)
    data["posts"].remove(p)
    commit("posts")
    return {"ok": True}


# ---------- 3. 반톡 ----------
@route("/api/class/send")
def class_send(me, body):
    ck = class_key(me)
    text = txt(body.get("text"), 1000)
    if not ck:
        raise ApiError("학년/반 정보가 없어서 반톡을 쓸 수 없어요")
    if not text:
        raise ApiError("메시지를 입력하세요")
    data["cm"].append({"id": new_id(data["cm"]), "uid": me["id"], "text": text, "t": now(), "ck": ck})
    commit("cm")
    return {"ok": True}


# ---------- 4. 1:1 채팅 (교사 <-> 학생만) ----------
@route("/api/dm/send")
def dm_send(me, body):
    to = user_by_id(body.get("to"))
    text = txt(body.get("text"), 1000)
    if not to or to["school"] != me["school"]:
        raise ApiError("대화 상대를 찾을 수 없어요", 404)
    if is_teacher(me) == is_teacher(to):
        raise ApiError("1:1 채팅은 교사와 학생 사이에만 가능해요", 403)
    if not text:
        raise ApiError("메시지를 입력하세요")
    key = "-".join(str(i) for i in sorted([me["id"], to["id"]]))
    data["dms"].setdefault(key, []).append({"uid": me["id"], "text": text, "t": now()})
    commit("dms")
    return {"ok": True}


# ---------- 5. 조별과제 ----------
@route("/api/group/create")
def group_create(me, body):
    if not is_teacher(me):
        raise ApiError("조별방은 교사만 만들 수 있어요", 403)
    name = txt(body.get("name"), 40)
    members = body.get("members")
    if not name or not isinstance(members, list) or not members:
        raise ApiError("조 이름과 조원을 선택하세요")
    for i in members:
        u = user_by_id(i)
        if not u or u["school"] != me["school"] or is_teacher(u):
            raise ApiError("조원은 같은 학교 학생만 가능해요")
    data["groups"].append({"id": new_id(data["groups"]), "name": name, "tid": me["id"],
                           "members": list(dict.fromkeys(members)), "msgs": []})
    commit("groups")
    return {"ok": True}


@route("/api/group/send")
def group_send(me, body):
    g = next((x for x in data["groups"] if x["id"] == body.get("gid")), None)
    text = txt(body.get("text"), 1000)
    if not g or not (g["tid"] == me["id"] or me["id"] in g["members"]):
        raise ApiError("조별방을 찾을 수 없어요", 404)
    if not text:
        raise ApiError("메시지를 입력하세요")
    g["msgs"].append({"uid": me["id"], "text": text, "t": now()})
    commit("groups")
    return {"ok": True}


# ---------- 6. 학생자치 논제 ----------
@route("/api/topic")
def topic_add(me, body):
    if not me["council"]:
        raise ApiError("논제 등록은 회장단만 가능해요", 403)
    text = txt(body.get("text"), 200)
    period = body.get("period") if body.get("period") in ("주간", "월간") else "주간"
    if not text:
        raise ApiError("논제를 입력하세요")
    data["topics"].append({"id": new_id(data["topics"]), "uid": me["id"], "period": period,
                           "text": text, "yes": [], "no": []})
    commit("topics")
    return {"ok": True}


@route("/api/topic/delete")
def topic_delete(me, body):
    t = next((x for x in data["topics"] if x["id"] == body.get("id")), None)
    if not t or not same_school(me, t["uid"]):
        raise ApiError("논제를 찾을 수 없어요", 404)
    if not (me["council"] or is_teacher(me)):
        raise ApiError("삭제 권한이 없어요", 403)
    data["topics"].remove(t)
    commit("topics")
    return {"ok": True}


@route("/api/topic/vote")
def topic_vote(me, body):
    t = next((x for x in data["topics"] if x["id"] == body.get("id")), None)
    kind = body.get("kind")
    if not t or not same_school(me, t["uid"]) or kind not in ("yes", "no"):
        raise ApiError("논제를 찾을 수 없어요", 404)
    t["yes"] = [i for i in t["yes"] if i != me["id"]]
    t["no"] = [i for i in t["no"] if i != me["id"]]
    t[kind].append(me["id"])
    commit("topics")
    return {"ok": True}


if __name__ == "__main__":
    # host="0.0.0.0": 같은 와이파이의 다른 기기도 접속 가능
    app.run(host="0.0.0.0", port=8002)
