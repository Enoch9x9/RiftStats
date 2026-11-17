"""用 GitHub REST API 把源码推上去。

为什么不用 git push：这台机器连不上 github.com:443，但 api.github.com 是通的，
所以走 Git Data API（blob → tree → commit → ref）一次性提交。

用法：
    $env:GH_TOKEN = "ghp_xxx"
    python tools/publish_github.py <仓库名> [--private] [--desc "描述"]
"""

from __future__ import annotations

import base64
import json
import time
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent.parent

INCLUDE_FILES = [
    "launch.py",
    "README.md",
    "LICENSE",
    "run.ps1",
    "build_portable.ps1",
    ".gitignore",
    "assets/riftstats.ico",
    "assets/riftstats.png",
]
INCLUDE_DIRS = ["app", "tools", "docs"]
SKIP_DIRS = {"__pycache__", "data", "shots", "samples", "libs", "dist", "build", ".tmp", ".git"}
SKIP_SUFFIX = {".pyc", ".log", ".spec", ".db", ".db-wal", ".db-shm"}


def api(method: str, path: str, body: dict | None = None, token: str = "") -> tuple[int, dict]:
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "riftstats-publisher")
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    last = None
    for attempt in range(10):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw.decode("utf-8", "ignore")[:300]}
            # 400/5xx 多半是连接被掐断导致请求体不完整，重试一次就好
            if exc.code in (400, 500, 502, 503, 504) and attempt < 9:
                wait = min(6.0, 0.8 * (attempt + 1))
                print("  HTTP %s，%.1f 秒后重试 %s %s" % (exc.code, wait, method, path), flush=True)
                time.sleep(wait)
                req = urllib.request.Request(url, data=data, method=method)
                req.add_header("Accept", "application/vnd.github+json")
                req.add_header("User-Agent", "riftstats-publisher")
                req.add_header("Authorization", f"Bearer {token}")
                if data:
                    req.add_header("Content-Type", "application/json")
                continue
            return exc.code, payload
        except Exception as exc:  # SSL EOF / 连接被重置，等一下重试
            last = exc
            wait = min(6.0, 0.8 * (attempt + 1))
            print("  网络抖动（%s），%.1f 秒后重试 %s %s" % (type(exc).__name__, wait, method, path), flush=True)
            time.sleep(wait)
            # 重建 Request，避免复用已坏的连接
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "riftstats-publisher")
            req.add_header("Authorization", f"Bearer {token}")
            if data:
                req.add_header("Content-Type", "application/json")
            req.add_header("Connection", "close")
    raise last


def collect() -> list[Path]:
    out: list[Path] = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.is_file():
            out.append(p)
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.suffix in SKIP_SUFFIX:
                continue
            out.append(p)
    return sorted(set(out))


def main() -> int:
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("缺少 GH_TOKEN 环境变量")
        return 2
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: publish_github.py <仓库名> [--private] [--desc 描述]")
        return 2
    repo = args[0]
    private = "--private" in sys.argv
    desc = "英雄联盟对局数据分析工具（本地、离线、可部署）"
    if "--desc" in sys.argv:
        desc = sys.argv[sys.argv.index("--desc") + 1]

    status, me = api("GET", "/user", token=token)
    if status != 200:
        print("token 无效:", status, me)
        return 1
    login = me["login"]
    print(f"账号: {login}")

    status, existing = api("GET", f"/repos/{login}/{repo}", token=token)
    if status == 404:
        status, created = api(
            "POST", "/user/repos",
            {"name": repo, "private": private, "description": desc, "auto_init": False},
            token=token,
        )
        if status not in (200, 201):
            print("建仓库失败:", status, created)
            return 1
        print(f"已新建仓库: {created.get('html_url')}")
        default_branch = created.get("default_branch") or "main"
        parent = None
    elif status == 200:
        print(f"仓库已存在: {existing.get('html_url')}")
        default_branch = existing.get("default_branch") or "main"
        status, ref = api("GET", f"/repos/{login}/{repo}/git/ref/heads/{default_branch}", token=token)
        parent = ref.get("object", {}).get("sha") if status == 200 else None
    else:
        print("查询仓库失败:", status, existing)
        return 1

    # 空仓库没法直接造 blob（409 Git Repository is empty），先用 Contents API 起一个初始提交
    if not parent:
        status, init = api(
            "PUT", f"/repos/{login}/{repo}/contents/README.md",
            {
                "message": "init",
                "content": base64.b64encode(b"# RiftStats\n").decode(),
                "branch": default_branch,
            },
            token=token,
        )
        if status in (200, 201):
            parent = init["commit"]["sha"]
            print("已建初始提交:", parent[:8])
        else:
            print("初始化仓库失败:", status, init)
            return 1

    files = collect()
    print(f"准备提交 {len(files)} 个文件")
    tree = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        status, blob = api(
            "POST", f"/repos/{login}/{repo}/git/blobs",
            {"content": base64.b64encode(p.read_bytes()).decode(), "encoding": "base64"},
            token=token,
        )
        if status not in (200, 201):
            print("上传失败:", rel, status, blob)
            return 1
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("  +", rel)

    status, new_tree = api(
        "POST", f"/repos/{login}/{repo}/git/trees", {"tree": tree}, token=token
    )
    if status not in (200, 201):
        print("建 tree 失败:", status, new_tree)
        return 1

    commit_body = {
        "message": "RiftStats: 英雄联盟对局数据台（客户端直连 + 分析 + 便携打包）",
        "tree": new_tree["sha"],
    }
    if parent:
        commit_body["parents"] = [parent]
    status, commit = api("POST", f"/repos/{login}/{repo}/git/commits", commit_body, token=token)
    if status not in (200, 201):
        print("建 commit 失败:", status, commit)
        return 1

    if parent:
        status, ref_out = api(
            "PATCH", f"/repos/{login}/{repo}/git/refs/heads/{default_branch}",
            {"sha": commit["sha"], "force": False}, token=token,
        )
    else:
        status, ref_out = api(
            "POST", f"/repos/{login}/{repo}/git/refs",
            {"ref": f"refs/heads/{default_branch}", "sha": commit["sha"]}, token=token,
        )
    if status not in (200, 201):
        print("更新分支失败:", status, ref_out)
        return 1

    print("完成:", f"https://github.com/{login}/{repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
