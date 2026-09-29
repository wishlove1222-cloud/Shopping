import html
import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

DATA_FILE = Path(__file__).parent / "shopping_list.json"

# 색은 rgba로 써서 라이트/다크 모드 어느 쪽에서도 자연스럽게 보이게 한다.
# 선택자는 버전마다 바뀌는 st-emotion-cache 클래스 대신
# data-testid와 key로 붙는 .st-key-<key> 클래스만 쓴다.
CSS = """
<style>
:root {
  --accent: #16a34a;
  --accent-soft: rgba(22, 163, 74, 0.10);
  --accent-line: rgba(22, 163, 74, 0.35);
  --line: rgba(128, 128, 128, 0.18);
  --soft: rgba(128, 128, 128, 0.06);
  --danger: #dc2626;
}
@media (prefers-color-scheme: dark) {
  :root { --accent: #22c55e; --danger: #f87171; }
}

/* 툴바(Deploy, 메뉴) 숨기기: config.toml toolbarMode의 보조 */
[data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; height: 0; }
.block-container { padding-top: 2.5rem; max-width: 680px; }

h1 { font-size: 2rem !important; letter-spacing: -0.02em; }

/* 진행 상황 카드 */
.st-key-progress_card {
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  border-radius: 14px;
  padding: 14px 18px 16px;
  gap: 0.5rem;
}
.progress-title { font-weight: 600; font-size: 1rem; }
.progress-title .count { color: var(--accent); }
.progress-sub { font-size: 0.85rem; opacity: 0.65; }

/* 입력 폼 */
[data-testid="stForm"] {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px;
}

/* 목록 */
.st-key-item_list { gap: 0.5rem; }

[class*="st-key-row_"], [class*="st-key-editrow_"] {
  background: var(--soft);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 6px 8px 6px 12px;
  transition: border-color 0.15s, background 0.15s;
}
[class*="st-key-row_"]:hover { border-color: var(--accent-line); }
[class*="st-key-editrow_"] {
  background: var(--accent-soft);
  border-color: var(--accent);
  padding: 8px;
}

/* 한 행이 휴대폰에서도 두 줄로 쪼개지지 않게: 줄바꿈 금지, 이름 칸만 늘어남 */
[class*="st-key-row_"] [data-testid="stHorizontalBlock"],
[class*="st-key-editrow_"] [data-testid="stHorizontalBlock"],
.st-key-add_row [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  align-items: center;
  gap: 0.4rem;
}
[class*="st-key-row_"] [data-testid="stColumn"],
[class*="st-key-editrow_"] [data-testid="stColumn"],
.st-key-add_row [data-testid="stColumn"] {
  min-width: 0 !important;
  width: auto !important;
  flex: 0 0 auto !important;
}
[class*="st-key-row_"] [data-testid="stColumn"]:nth-child(2),
[class*="st-key-editrow_"] [data-testid="stColumn"]:nth-child(1),
.st-key-add_row [data-testid="stColumn"]:nth-child(1) {
  flex: 1 1 0 !important;
}
[class*="st-key-editrow_"] [data-testid="stColumn"]:nth-child(2),
.st-key-add_row [data-testid="stColumn"]:nth-child(2) {
  flex: 0 0 28% !important;
}

/* 아이템 이름과 수량 배지 */
.item { display: flex; align-items: center; gap: 0.5rem; min-height: 2rem; }
.item .name { font-weight: 500; overflow-wrap: anywhere; line-height: 1.35; }
.item .qty {
  flex: none;
  font-size: 0.78rem;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(128, 128, 128, 0.14);
  opacity: 0.85;
  white-space: nowrap;
}
.item.done .name, .item.done .qty { text-decoration: line-through; opacity: 0.45; }

/* ✏️ / 🗑️ 아이콘 버튼 */
[class*="st-key-edit_"] button, [class*="st-key-del_"] button {
  min-height: 2rem;
  padding: 0 0.45rem;
  border-radius: 8px;
}
[class*="st-key-edit_"] button:hover { background: rgba(128, 128, 128, 0.14); }
[class*="st-key-del_"] button:hover {
  background: rgba(220, 38, 38, 0.14);
  color: var(--danger);
}

/* 완료 항목 모두 삭제: 눈에 덜 띄는 보조 버튼 */
.st-key-clear_checked button {
  font-size: 0.85rem;
  opacity: 0.7;
}
.st-key-clear_checked button:hover { opacity: 1; color: var(--danger); }
.st-key-clear_checked { align-items: center; }
</style>
"""


# ---------- 저장 / 불러오기 ----------
# 여러 탭(세션)이 같은 파일을 쓰므로, 파일은 항상 "잠금 → 다시 읽기 → 수정 → 저장" 순서로 다룬다.
# 세션이 들고 있는 오래된 목록으로 파일을 덮어쓰면 다른 탭의 변경이 사라진다. (REVIEW.md 버그 1)
@st.cache_resource
def file_lock():
    # 스크립트는 매번 다시 실행되므로 잠금은 cache_resource로 서버 전체에서 하나만 만든다.
    return threading.RLock()


def notify(message):
    st.session_state.setdefault("notices", []).append(message)


def quarantine_data_file():
    # 읽을 수 없는 파일은 지우지 않고 옆으로 옮겨 둔다.
    backup = DATA_FILE.with_name(f"shopping_list.broken-{datetime.now():%Y%m%d-%H%M%S}.json")
    os.replace(DATA_FILE, backup)
    return backup


def normalize_items(raw):
    """파일 내용을 {id, name, quantity, checked} 목록으로 맞춘다. (정리된 목록, 버린 개수)를 돌려준다."""
    if not isinstance(raw, list):
        raise ValueError("목록 형식이 아님")
    items, dropped = [], 0
    for entry in raw:
        name = str(entry.get("name") or "").strip() if isinstance(entry, dict) else ""
        if not name:
            dropped += 1
            continue
        items.append({
            "id": str(entry.get("id") or uuid.uuid4().hex),
            "name": name,
            "quantity": str(entry.get("quantity") or "").strip(),
            "checked": bool(entry.get("checked", False)),
        })
    return items, dropped


def load_items():
    with file_lock():
        if not DATA_FILE.exists():
            return []
        text = DATA_FILE.read_text(encoding="utf-8-sig")  # 메모장 등이 붙이는 BOM 허용
        if not text.strip():
            return []
        try:
            items, dropped = normalize_items(json.loads(text))
        except ValueError:
            backup = quarantine_data_file()
            notify(f"저장 파일을 읽을 수 없어서 빈 목록으로 시작해요. 원래 파일은 {backup.name}에 보관했어요.")
            return []
        if dropped:
            backup = DATA_FILE.with_name(f"shopping_list.broken-{datetime.now():%Y%m%d-%H%M%S}.json")
            backup.write_text(text, encoding="utf-8")
            notify(f"읽을 수 없는 항목 {dropped}개를 건너뛰었어요. 원래 파일은 {backup.name}에 보관했어요.")
        if dropped or items != json.loads(text):
            # 빠진 id 등을 채웠으면 바로 저장해서 다음 실행에도 같은 id가 쓰이게 한다.
            save_items(items)
        return items


def save_items(items):
    # 임시 파일에 다 쓴 뒤 한 번에 바꿔치기: 저장 도중 꺼져도 파일이 반쯤 남지 않는다. (REVIEW.md 버그 3)
    with file_lock():
        tmp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, DATA_FILE)
                break
            except PermissionError:  # Windows에서 다른 프로그램이 잠깐 파일을 잡고 있을 때
                if attempt == 4:
                    raise
                time.sleep(0.05)


def modify_items(change):
    """파일을 다시 읽어 change(items)를 적용하고 저장한다. change는 바뀐 게 있으면 True를 돌려준다."""
    with file_lock():
        items = load_items()
        changed = change(items)
        if changed:
            save_items(items)
    st.session_state.shopping_items = items
    return changed


def new_item(name, quantity=""):
    return {"id": uuid.uuid4().hex, "name": name, "quantity": quantity, "checked": False}


def find_item(items, item_id):
    return next((i for i in items if i["id"] == item_id), None)


def item_html(item):
    # st.html은 마크다운을 해석하지 않으므로 HTML 이스케이프만 하면
    # 사용자가 입력한 *, ~, <b> 같은 기호가 그대로 보인다.
    qty = f'<span class="qty">{html.escape(item["quantity"])}</span>' if item["quantity"] else ""
    done = " done" if item["checked"] else ""
    return f'<div class="item{done}"><span class="name">{html.escape(item["name"])}</span>{qty}</div>'


# ---------- 기능 ----------
# 모두 id로 찾아서 바꾼다. 다른 탭에서 이미 지운 아이템이면 되살리지 않는다.
def add_item(name, quantity):
    modify_items(lambda items: items.append(new_item(name, quantity)) or True)


def update_item(item_id, name, quantity):
    def change(items):
        item = find_item(items, item_id)
        if item:
            item["name"] = name
            item["quantity"] = quantity
        return item is not None

    if not modify_items(change):
        notify("다른 곳에서 이미 삭제된 아이템이라 저장하지 못했어요.")
    st.session_state.editing_id = None


def delete_item(item_id):
    def change(items):
        before = len(items)
        items[:] = [i for i in items if i["id"] != item_id]
        return len(items) != before

    modify_items(change)
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None


def toggle_item(item_id):
    # 뒤집지 않고 체크박스의 새 값으로 맞춘다: 다른 탭이 이미 바꿔 놨어도 누른 대로 된다.
    checked = st.session_state[f"chk_{item_id}"]

    def change(items):
        item = find_item(items, item_id)
        if item is None:
            return False
        item["checked"] = checked
        return True

    if not modify_items(change):
        notify("다른 곳에서 이미 삭제된 아이템이에요.")


def clear_checked():
    def change(items):
        before = len(items)
        items[:] = [i for i in items if not i["checked"]]
        return len(items) != before

    modify_items(change)


# ---------- 초기화 ----------
st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒")
st.html(CSS)

# 키 이름을 "items"로 쓰면 안 된다: st.session_state.items는 내장 메서드 items()를 가리킨다.
# 매 실행마다 파일을 다시 읽어서 다른 탭의 변경도 반영한다.
st.session_state.shopping_items = load_items()
if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

items = st.session_state.shopping_items

# 수정 중이던 아이템이 다른 탭에서 삭제됐으면 수정 모드를 푼다.
if st.session_state.editing_id and not find_item(items, st.session_state.editing_id):
    st.session_state.editing_id = None
    notify("수정하던 아이템이 다른 곳에서 삭제됐어요.")

# ---------- 화면 ----------
st.title("🛒 쇼핑 리스트")

for message in st.session_state.pop("notices", []):
    st.warning(message)

# 진행 상황 (F-6)
done = sum(i["checked"] for i in items)
if items:
    with st.container(key="progress_card"):
        if done == len(items):
            st.html('<div class="progress-title">장보기 완료! 🎉</div>'
                    f'<div class="progress-sub">{len(items)}개 모두 샀어요</div>')
        else:
            st.html(f'<div class="progress-title"><span class="count">{done} / {len(items)}개</span> 구매 완료</div>'
                    f'<div class="progress-sub">{len(items) - done}개 남았어요</div>')
        st.progress(done / len(items))

# 추가 (F-1)
with st.form("add_form", clear_on_submit=True, border=False):
    with st.container(key="add_row"):
        c1, c2, c3 = st.columns([4, 2, 1], vertical_alignment="center")
        name = c1.text_input("아이템", placeholder="예: 우유", label_visibility="collapsed")
        qty = c2.text_input("수량", placeholder="수량", label_visibility="collapsed")
        submitted = c3.form_submit_button("추가", type="primary")

if submitted:
    if name.strip():
        add_item(name.strip(), qty.strip())
        st.rerun()
    else:
        st.warning("아이템 이름을 입력하세요.")

# 목록
if not items:
    st.info("쇼핑 리스트가 비어 있어요. 위에서 아이템을 추가해 보세요!")  # F-8

with st.container(key="item_list"):
    for item in items:
        iid = item["id"]

        if st.session_state.editing_id == iid:
            # 수정 모드 (F-2)
            with st.container(key=f"editrow_{iid}"):
                c1, c2, c3, c4 = st.columns([4, 2, 1, 1], vertical_alignment="center")
                new_name = c1.text_input(
                    "이름", item["name"], key=f"name_{iid}", label_visibility="collapsed"
                )
                new_qty = c2.text_input(
                    "수량", item["quantity"], key=f"qty_{iid}", label_visibility="collapsed"
                )
                save_clicked = c3.button("저장", key=f"save_{iid}", type="primary")
                cancel_clicked = c4.button("취소", key=f"cancel_{iid}")
            if save_clicked:
                if new_name.strip():
                    update_item(iid, new_name.strip(), new_qty.strip())
                    st.rerun()
                else:
                    st.warning("아이템 이름을 입력하세요.")
            if cancel_clicked:
                st.session_state.editing_id = None
                st.rerun()
        else:
            # 보기 모드
            with st.container(key=f"row_{iid}"):
                c1, c2, c3, c4 = st.columns([0.6, 5.4, 1, 1], vertical_alignment="center")
                # 위젯이 기억하는 값 대신 파일 값을 쓴다: 다른 탭에서 바뀐 체크 상태도 그대로 보이게.
                st.session_state[f"chk_{iid}"] = item["checked"]
                c1.checkbox(  # F-4
                    "완료",
                    key=f"chk_{iid}",
                    on_change=toggle_item,
                    args=(iid,),
                    label_visibility="collapsed",
                )
                c2.html(item_html(item))
                edit_clicked = c3.button("✏️", key=f"edit_{iid}", type="tertiary")
                del_clicked = c4.button("🗑️", key=f"del_{iid}", type="tertiary")  # F-3
            if edit_clicked:
                st.session_state.editing_id = iid
                st.rerun()
            if del_clicked:
                delete_item(iid)
                st.rerun()

# 완료 항목 일괄 삭제 (F-7)
if done:
    st.button("완료 항목 모두 삭제", key="clear_checked", on_click=clear_checked, type="tertiary")
