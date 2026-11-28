#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-body CT6 volatile RAM step runner for OpenGate Studio (zve1_202, a7s3_501, fx3_702, a7c_203, zve10_203)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import posixpath
import re
import struct
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KITS_DIR = REPO_ROOT / "kits"
SRC_DIR = REPO_ROOT / "src"
CT1_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT1_usb_first_contact"
CT6_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT6_memory_read_check"

for _p in (HERE, CT1_DIR, CT6_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ct1_common as c  # noqa: E402
import ct1_sim  # noqa: E402
import ct6_level1_run as R  # noqa: E402
import studio_cineprobe  # noqa: E402

BODY_CONFIG: dict[str, dict[str, str]] = {
    "zve1_202": {
        "prefix": "zv",
        "model": "ZV-E1",
        "header_model": "ZV-E1",
        "reader": "zvread",
        "firmware": "2.02",
        "expected_json": "zv_expected.json",
        "report_name": "zv_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "On the ZV-E1 the power switch undoes only part of it (the encoder side stays): keep the camera on between steps."
        ),
    },
    "a7s3_501": {
        "prefix": "s3",
        "model": "ILCE-7SM3",
        "header_model": "ILCE-7SM3",
        "reader": "s3read",
        "firmware": "5.01",
        "expected_json": "s3_expected.json",
        "report_name": "s3_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "On the a7S III (5.01), toggling the power switch resets coprocessor RAM while retaining encoder patches: always pull the battery >= 10s to restore stock, and keep the camera on between steps."
        ),
    },
    "fx3_702": {
        "prefix": "fx3",
        "model": "ILME-FX3",
        "header_model": "ILME-FX3",
        "reader": "fx3read",
        "firmware": "7.02",
        "expected_json": "fx3_expected.json",
        "report_name": "fx3_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "On the FX3 / a7S III coprocessor software the power switch may clear only part of it: keep the camera on between steps, and pull the battery >= 10s to restore stock."
        ),
    },
    "a7c_203": {
        "prefix": "a7c",
        "model": "ILCE-7C",
        "header_model": "ILCE-7C",
        "reader": "a7cread",
        "firmware": "2.03",
        "expected_json": "a7c_expected.json",
        "report_name": "a7c_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "Keep the camera powered on between steps, and pull the battery >= 10s to restore stock."
        ),
    },
    "zve10_203": {
        "prefix": "zve10",
        "model": "ZV-E10",
        "header_model": "ZV-E10",
        "reader": "zve10read",
        "firmware": "2.03",
        "expected_json": "zve10_expected.json",
        "report_name": "zve10_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "Keep the camera powered on between steps, and pull the battery >= 10s to restore stock."
        ),
    },
}

STEP_LEVEL_BASE: dict[str, int] = {
    "L": 200,
    "S": 300,
    "C": 400,
    "M": 500,
    "V": 600,
    "H": 700,
    "B": 800,
    "I": 900,
    "P": 1000,
    "Q": 1100,
    "F": 1200,
}

MultiStepGuard = R.MultiStepGuard
VALID_READER_PREFIXES: tuple[str, ...] = tuple(f"{cfg['reader']} " for cfg in BODY_CONFIG.values())

# Superseded studio + upstream ArcaneLantern helper SHA-256 hashes (auto-cleaned if left on /tmp/jiritsu/libJit.so).
EARLIER_LIBS: dict[str, str] = {
    # Superseded fx3_702 studio builds
    "9fd94c179f8c7b721600313a1e7a7f2a173a1a3dae24319fe4411cba4dac5946": "earlier fx3_702 L5 (libJit_fx3_L5.so)",
    "6c8544fb91879ba4c1b8ce9351826253b61557d797466f836e4e8e65b0acf3b6": "earlier fx3_702 L6 (libJit_fx3_L6.so)",
    "47400649ac29ac03fd77b4805e0a41c60b4a3cfa1ae5e3f384f0d33a0b503050": "earlier fx3_702 L19 (libJit_fx3_L19.so)",
    "6ca3ee7df282bda70bc50bb4f9284ccc622c2c20e6ab64b964a949148a33d836": "earlier fx3_702 L20 (libJit_fx3_L20.so)",
    "f134ab54bdd485eff7643df63b9f59d4d1d7ce9040273183788c2fdd687063b5": "earlier fx3_702 V19 (libJit_fx3_V19.so)",
    "cf215b6115089b9d860b5fc6b09f9e4d69919f6c90f60ae7f24fe9b33afd853e": "earlier fx3_702 V20 (libJit_fx3_V20.so)",
    "616d24d147dbf646deb0df3257ceeab39790e03bc301645b69852917c8e9813e": "earlier fx3_702 B19 (libJit_fx3_B19.so)",
    "040341f109d2b1ba956558cdaa665a839faef81dc53c8f3e4ba125949903e26d": "earlier fx3_702 B20 (libJit_fx3_B20.so)",
    "ccfd54779e384a5b903ca880d4f9a559d2a8b0077b03a72bdb8ac59cf8e19321": "earlier fx3_702 I19 (libJit_fx3_I19.so)",
    "32c4d2d168224ef16ba75025d92a79c135ac34437f3767e2b32fa67cd556161c": "earlier fx3_702 I20 (libJit_fx3_I20.so)",
    # Superseded a7s3_501 studio builds
    "5bc1bdcee924e1bd30e405fc29c269440b2c36548ede357d8e34c5d21cc4efa3": "earlier a7s3_501 L5 (libJit_s3_L5.so)",
    "5ea7f7cac2a2bda8628a3dda9012532c7c508f6ea5ce9603021474ee5249f69c": "earlier a7s3_501 L6 (libJit_s3_L6.so)",
    "85b5882d0fd2f2525a6eab109ed7ee8ea2f53be42351b56af52e2e7f7f47d588": "earlier a7s3_501 L19 (libJit_s3_L19.so)",
    "3683c64f54784cfb7fde5af0c4b4096cb6cd3d58cc9c3d988c92abd1c9358f86": "earlier a7s3_501 L20 (libJit_s3_L20.so)",
    "3ef580f51952b458f3191fb08190311544f5fdc188b0151c5c0a57737bfc52c3": "earlier a7s3_501 V19 (libJit_s3_V19.so)",
    "145af3e92df71648b15cd6fabd569963d3d990f1bd5f32df822a0a0688791653": "earlier a7s3_501 V20 (libJit_s3_V20.so)",
    "07afc62ff0fcfe6f3f207d90ed88e4b84e0edb1fd7c6a2ae02e9a4bc8c5888ba": "earlier a7s3_501 B19 (libJit_s3_B19.so)",
    "f1d6a368322019d19411948e74edba6ced6cf4f56dc95a2ebec1f825b72f218f": "earlier a7s3_501 B20 (libJit_s3_B20.so)",
    "dc3e9bec05aa6ea665a88e1c155ce6430c93c4c55a1ec118b4bf7e732dacbec7": "earlier a7s3_501 I19 (libJit_s3_I19.so)",
    "cdcccfee1a9ca2f0fb0c09c50dbd8c09561bdb644fe5a74c1e317a1d714bf371": "earlier a7s3_501 I20 (libJit_s3_I20.so)",
    # Superseded zve1_202 studio builds
    "5d419a3222f413b01a05c3dcf27f85c3cd2de16354f44d4feae79a084edfae47": "earlier zve1_202 L5 (libJit_zv_L5.so)",
    "0850515ead1d11214509974f30edc22889db23a6fa81cc4a67b236883f6dc9e6": "earlier zve1_202 L6 (libJit_zv_L6.so)",
    "4341773dcfb1cb922379075ed2760f75e9443e7a9127f9ae80ddd5ebff895c26": "earlier zve1_202 L19 (libJit_zv_L19.so)",
    "f54bb2855db9fe4e7d48c7eec06f67b9b9c218ebe8fb839ad4e219406df9a987": "earlier zve1_202 L20 (libJit_zv_L20.so)",
    "657ea733c8574c6a2d9ab6961f09c513c219a4a588375f34348e0e284da69f01": "earlier zve1_202 V19 (libJit_zv_V19.so)",
    "e77f71adfd1850944aeff91c5ba210f7cfeddadcb5582cc931bbd5c2e8ba98c3": "earlier zve1_202 V20 (libJit_zv_V20.so)",
    "974e2624d0cf34862deb2585606715893af026fc0201c2e47d5f65083a3637a6": "earlier zve1_202 B19 (libJit_zv_B19.so)",
    "7d1bfb6eaaa6d08438522fbf56138f572a49f431cea5b87dbf0599749837da72": "earlier zve1_202 B20 (libJit_zv_B20.so)",
    "8c9640e98f817420502b33d2723e8030f4a6db4d6bae007323fb38735db91f28": "earlier zve1_202 I19 (libJit_zv_I19.so)",
    "5a623fcdfd7ea86b8b8a65a640a3cd75fff58db9d0322053501d3eb5137d9466": "earlier zve1_202 I20 (libJit_zv_I20.so)",
    # Upstream ArcaneLantern prebuilt helpers (check/dump across fx3, a7siii, zve1)
    "fcf97a8ea56abee543734779b8cac10267b4b33adda863a4032c11436e6d78ce": "upstream fx3 check (libJit_fx3_check.so)",
    "ad2bae7922865dd7faf3bce59aa4114e53fe56ce4366b133c96ce91414592527": "upstream fx3 dump (libJit_fx3_dump.so)",
    "e8adeae97caab3b26958068de0dcf1dacd76ad8483333b5cf23f91743d6a91dc": "upstream a7siii check (libJit_s3_check.so)",
    "ad416c29151f435f45aa71c6bb8f4bb9cf24c85bf098945642e92bf76f37f91c": "upstream a7siii dump (libJit_s3_dump.so)",
    "c25e08bf01dbd4e314d91a54aa39ec450c2326e43030df6c8277e73b57a508e0": "upstream zve1 check (libJit_zv_check.so)",
    "30aab4055212647723c26e8d5332e926fe73cb6898370aa28496799576996421": "upstream zve1 dump (libJit_zv_dump.so)",
    # Superseded v0.1.3-alpha (417b28a) helpers before L3-nrt-vline NrtMetaWrapper::Init update
    "fd78700bec66c78cd13e421adfc52ea1b5d3c418711c69571cf0a1d9ad9cf627": "v0.1.3-alpha zve1_202 check (libJit_zv_check.so)",
    "2b676263ccb09969cd2f8fce985578593fd0756f11198e25faef840e88733cfe": "v0.1.3-alpha zve1_202 dump (libJit_zv_dump.so)",
    "a2c3cda80851abf0f6a592de817c365cdaf0143325d7f70af4fac114bb29f31a": "v0.1.3-alpha zve1_202 V19 (libJit_zv_ogfile2560_hs_s_v3.so)",
    "796f58d4ef240e90a9bda244f66da884c320f48d34ce19bbe87831c8cc279777": "v0.1.3-alpha zve1_202 V20 (libJit_zv_ogfile2560_hs_s_v3_60p.so)",
    "413c968dbc583d218594cd9d09e653305f04396e880c665a33eab6e1d0756d35": "v0.1.3-alpha zve1_202 I19 (libJit_zv_ogfile2560_i.so)",
    "058b41f320c49181df1d0dba4f42d340cc509eb6c81d12c09d3fab68191062e4": "v0.1.3-alpha zve1_202 I20 (libJit_zv_ogfile2560_i_60p.so)",
    "d80e4e951c33b9a3bdddc99a4996a666951eed9a276fe842534f57346328480a": "v0.1.3-alpha a7s3_501 check (libJit_s3_check.so)",
    "68790cda22525c1f54b270403c8aa611599e927518454416b4d7fb4f0e1e808f": "v0.1.3-alpha a7s3_501 dump (libJit_s3_dump.so)",
    "68a33c49b145cdfd39c28c390e669b34d24d74c78dc0f45d5ffadbd93a1e8d18": "v0.1.3-alpha a7s3_501 V19 (libJit_s3_ogfile2560_hs_s_v3.so)",
    "e78762128deeb703ed9b40f00397eeb0428722fe9761d0ab5a755c016dcda4c9": "v0.1.3-alpha a7s3_501 V20 (libJit_s3_ogfile2560_hs_s_v3_60p.so)",
    "ab4bdee0c1aaa38b4635a9c500680e66ebef5dffe2f7a6a9ee55119e3f041e47": "v0.1.3-alpha fx3_702 check (libJit_fx3_check.so)",
    "15e35b234e17a06a1ee72f51e20ab40fbcf8feabc6ccfa87c24834de7b0818b2": "v0.1.3-alpha fx3_702 dump (libJit_fx3_dump.so)",
    "4f3be4553237ded7091d88410ddc7b6b4b086308e956db7b64681ca31e8ffdbd": "v0.1.3-alpha fx3_702 V19 (libJit_fx3_ogfile2560_hs_s_v3.so)",
    "2670d65b38a3a17c0a5600e605afdc2f3697324aca2d81d395a02e50f89bd32e": "v0.1.3-alpha fx3_702 V20 (libJit_fx3_ogfile2560_hs_s_v3_60p.so)",
    "51cc4c86d2d2f40436dd02dc2b101bf0dcdb6ad88d726b64156c696695987941": "v0.1.3-alpha fx3_702 I19 (libJit_fx3_ogfile2560_i.so)",
    "9d0ea28bbd768315553d47486ed810c62518d7e00faf34033065a004a1a95f1c": "v0.1.3-alpha fx3_702 I20 (libJit_fx3_ogfile2560_i_60p.so)",
    "4c1892e449447d42d32d1e5d27ac2a9e6aa2a5520cd6d48f84ad71ae7cd912ac": "upstream a7c (libJit_a7c_L16.so)",
    "54efa61db10f1857a59c6d9d1b99af81b1fdbd7d99050c6358d552cec70431d0": "upstream a7c (libJit_a7c_L17.so)",
    "dc57b8b58487b68c8f11faf265106aa016c683bf8baedbc540335a313208b895": "upstream a7c (libJit_a7c_L19.so)",
    "c0bad2f024e05a0d8c4e4bbce69e35b15f7f525cdb3209133ecf2189583eb10b": "upstream a7c (libJit_a7c_L20.so)",
    "4deb370a3376a99477146afec7d8292462215a1f98f5716e3f841071f41ff5ba": "upstream a7c (libJit_a7c_L5.so)",
    "9606475c32a27999ed74748baac1a89616f92105857dff35eec01a03efa5f931": "upstream a7c (libJit_a7c_L6.so)",
    "41f1f28a0388ab9642b326b84f2d129cccdb4d2ec65abda0a58a6dfc46e04a81": "upstream a7c (libJit_a7c_check.so)",
    "4f88f9bc2615855b05dc340fb7549660c1e97f8a22bfc23298ed052765364090": "upstream a7c (libJit_a7c_dump.so)",
    "78b01eb1397f708d6aea397080ac33c6b6c6aee9cee7981627ebe949f3a731e5": "upstream zve10 (libJit_zve10_L16.so)",
    "f64e55b1348c8c6b7634bb6abf335d94aae07cf9b3eec3499adc698307ba8f62": "upstream zve10 (libJit_zve10_L17.so)",
    "714ffb1315280d019c53248cbd6ddc9af20701854aacc576818fb8e49edbf7d1": "upstream zve10 (libJit_zve10_L19.so)",
    "b89aa077025f2827a8eeffc95904c69891620a8b8efbd3380931f23cc6efb7be": "upstream zve10 (libJit_zve10_L20.so)",
    "971fa595d65cc518dd1615e7a1f2b7591dad1e75535da4b9104c164f4c2a3f77": "upstream zve10 (libJit_zve10_L5.so)",
    "196cdf731cd21860256cbb772467f20749ea6e3b1721841c70d51bf824e2ebf6": "upstream zve10 (libJit_zve10_L6.so)",
    "fc8dd57f6f373fb9695493b9d2e4c9260f846bfbc9b79f2a02be0b42a3959e46": "upstream zve10 (libJit_zve10_check.so)",
    "06f163b51d828b4bfb787816302b37cb2c4065bac60b70246da1139efaa1e678": "upstream zve10 (libJit_zve10_dump.so)",
}
EXTRA_LIBS: dict[str, str] = {}

# Active context configured by use()
CURRENT_BODY: str = "zve1_202"
CURRENT_WHICH: str = "check"
CURRENT_KIT_DIR: Path = KITS_DIR / "zve1_202"
CURRENT_MANIFEST: dict[str, Any] = {}
CURRENT_EXPECTED: dict[str, Any] = {}
CURRENT_WRITE_STEPS: dict[str, tuple[str, str, str]] = {}


def private_root() -> Path:
    return Path(os.environ.get("OPENGATE_CAMERA_PRIVATE") or c.PRIVATE_ROOT)


def load_body_manifest(body_id: str) -> tuple[Path, dict[str, Any]]:
    if body_id not in BODY_CONFIG:
        raise ValueError(f"Unsupported body_id: {body_id!r}")
    kit_dir = KITS_DIR / body_id
    man_path = kit_dir / "manifest.json"
    if not man_path.is_file():
        raise FileNotFoundError(f"Missing manifest: {man_path}")
    with man_path.open("r", encoding="utf8") as f:
        return kit_dir, json.load(f)


def load_body_expected(body_id: str) -> dict[str, Any]:
    cfg = BODY_CONFIG[body_id]
    exp_path = SRC_DIR / body_id / cfg["expected_json"]
    if not exp_path.is_file():
        raise FileNotFoundError(f"Missing expected JSON: {exp_path}")
    with exp_path.open("r", encoding="utf8") as f:
        return json.load(f)


def step_level(which: str) -> int:
    if which == "check":
        return 101
    if which == "dump":
        return 102
    if which == "cineprobe":
        return 103
    if len(which) < 2 or which[0] not in STEP_LEVEL_BASE or not which[1:].isdigit():
        raise ValueError(f"Unsupported step name: {which!r}")
    return STEP_LEVEL_BASE[which[0]] + int(which[1:])


def step_pins(manifest: dict[str, Any]) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str, str]]]:
    pins: dict[str, tuple[str, str]] = {}
    for k in ("check", "dump", "cineprobe"):
        entry = manifest.get("readonly", {}).get(k)
        if isinstance(entry, dict):
            pins[k] = (entry["file"], entry["sha256"])
    write_steps: dict[str, tuple[str, str, str]] = {}
    for k, entry in manifest.get("steps", {}).items():
        pins[k] = (entry["file"], entry["sha256"])
        write_steps[k] = (entry["file"], entry["sha256"], entry.get("summary", k))
    return pins, write_steps


_BENIGN_DIAG_SECTION_PREFIXES = (
    "== dir /proc/driver/pcie",
    "== file /proc/driver/pcie/",
    "== dir /sys/module/liro/parameters",
    "== file /sys/module/liro/parameters/",
    "== dir /log",
    "== file /log/",
)
_BENIGN_DIAG_BANG_RE = re.compile(
    r"^!! (?:read failed -21|open failed -\d+|truncated at \d+ bytes)$"
)


def _partition_problem_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split '!!' lines into (actionable_problems, benign_diagnostic_preamble_notices).

    Fail closed: any '!!' line inside action/verification sections ('== level ',
    '== identity:', '== coprocessor', '== main-processor', '== summary') or outside
    the known optional diagnostic directory dumps stays in actionable_problems.
    """
    problems: list[str] = []
    diag_problems: list[str] = []
    current_section = ""
    in_action_area = False
    for ln in lines:
        if ln.startswith("== "):
            current_section = ln
            if ln.startswith(("== level ", "== identity:", "== coprocessor", "== main-processor", "== summary")):
                in_action_area = True
        elif ln.startswith("!!"):
            if (
                not in_action_area
                and current_section.startswith(_BENIGN_DIAG_SECTION_PREFIXES)
                and _BENIGN_DIAG_BANG_RE.match(ln)
            ):
                diag_problems.append(ln)
            else:
                problems.append(ln)
    return problems, diag_problems


def parse_write_result(which: str, what: str, data: bytes) -> dict[str, Any]:
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    pick = lambda start: next((ln for ln in lines if ln.startswith(start)), None)
    outcome = (
        "UNDO INCOMPLETE"
        if (pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE"))
        else "DONE"
        if pick("DONE: ")
        else "NOTHING TO DO"
        if pick("NOTHING TO DO")
        else "NOT DONE (everything put back)"
        if pick("NOT DONE: ")
        else "NOTHING WRITTEN"
        if any("nothing is written" in ln for ln in lines)
        else "UNKNOWN"
    )
    problems, diag_problems = _partition_problem_lines(lines)
    header_ok = bool(lines) and lines[0].startswith(f"readcheck 1 level {which[1:]}")
    has_level_section = any(ln.startswith(f"== level {which[1:]}") for ln in lines)
    complete = any(ln.startswith("== done") for ln in lines[-3:])
    ok = outcome in ("DONE", "NOTHING TO DO") and header_ok and has_level_section and complete and not problems
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_ok": header_ok,
        "euid": "see the result",
        "sections": [ln for ln in lines if ln.startswith("== ")],
        "problems": len(problems),
        "complete": complete,
        "s3": {
            "step": which,
            "what": what,
            "outcome": outcome,
            "ok": ok,
            "outcome_line": (
                pick("DONE: ")
                or pick("NOTHING TO DO")
                or pick("NOT DONE: ")
                or pick("!! UNDO INCOMPLETE")
                or pick("UNDO INCOMPLETE")
            ),
            "problem_lines": problems,
            "diagnostic_problem_lines": diag_problems,
        },
    }


def parse_readonly_result(
    body_id: str,
    which: str,
    data: bytes,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if which == "cineprobe":
        return studio_cineprobe.parse_cineprobe_report(body_id, data, spec)
    cfg = BODY_CONFIG[body_id]
    if spec is None:
        spec = load_body_expected(body_id)
    fw = cfg["firmware"]
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    head = lines[0] if lines else ""
    expected_header = f"{cfg['reader']} {spec['label']} {which} for {cfg['header_model']} {fw}; read-only"
    header_ok = head == expected_header
    complete = "== done" in lines[-3:] and lines[-3:].count("== done") == 1
    problem_lines, diag_problems = _partition_problem_lines(lines)

    same_pat = re.compile(rf" sha256 ([0-9a-f]{{64}})  SAME as the {re.escape(fw)} update$", re.M)
    diff_pat = re.compile(rf"DIFFERS from the {re.escape(fw)} update$")
    same_hashes = same_pat.findall(text)
    identity_differs = sum(1 for ln in lines if diff_pat.search(ln))
    expected_id_hashes = [*spec["id_files"].values(), *spec["id_pages"].values()]
    identity_ok = identity_differs == 0 and sorted(same_hashes) == sorted(expected_id_hashes)

    pages: dict[int, tuple[str, bytes]] = {}
    for ln in lines:
        if ln.startswith(("cppage ", "ddrpage ")):
            _, name, addr, hx = ln.split(" ", 3)
            pages[int(addr, 16)] = (name, bytes.fromhex(hx.strip()))

    sites: list[dict[str, Any]] = []
    site_lines_count = 0
    for ln in lines:
        if ln.startswith("site "):
            site_lines_count += 1
            m = re.match(
                r"site (\S+) (0x[0-9a-f]+) len (\d+)(?: bytes (?:differing from stock )?(\S+))?  (STOCK|TARGET|OTHER.*|NOT READ)$",
                ln,
            )
            if m:
                sites.append({
                    "name": m.group(1),
                    "address": m.group(2),
                    "length": int(m.group(3)),
                    "shown": m.group(4),
                    "state": m.group(5),
                })

    cp_ok = len(sites) == site_lines_count == len(spec["cp_sites"])
    if cp_ok:
        expected_cp = {int(row["address"], 16): row for row in spec["cp_sites"]}
        for row in sites:
            want = expected_cp.pop(int(row["address"], 16), None)
            if not want or row["length"] != want["length"] or row["name"] != want["name"]:
                cp_ok = False
                break
            st = row["state"]
            is_fx3_screen = body_id == "fx3_702" and want["name"].startswith("screen")
            if not want["soft"] or is_fx3_screen:
                if st not in ("STOCK", "TARGET"):
                    cp_ok = False
                    break
            else:
                if st not in ("STOCK", "TARGET", "OTHER (not counted: filled at run time)"):
                    cp_ok = False
                    break
        if expected_cp:
            cp_ok = False

    lm_lines = [ln for ln in lines if ln.startswith("lm ")]
    av_lines = [ln for ln in lines if ln.startswith("av ")]
    lm_stock = sum(1 for ln in lm_lines if ln.endswith("  STOCK"))
    lm_target = sum(1 for ln in lm_lines if ln.endswith("  TARGET"))
    lm_other = len(lm_lines) - lm_stock - lm_target
    av_stock = sum(1 for ln in av_lines if ln.endswith("  STOCK"))
    av_target = sum(1 for ln in av_lines if ln.endswith("  TARGET"))
    av_other = len(av_lines) - av_stock - av_target
    mp_ok = (
        len(lm_lines) == spec["lm_sites"]
        and len(av_lines) == spec["av_sites"]
        and lm_other == 0
        and av_other == 0
    )

    guard_lines = [ln for ln in lines if ln.startswith("guard ")]
    same_guards = [ln.split()[1] for ln in guard_lines if ln.endswith("  SAME")]
    guards_ok = len(same_guards) == len(guard_lines) and sorted(same_guards) == sorted(spec["av_guards"])

    verdicts = [ln for ln in lines if ln.startswith("VERDICT ")]
    all_checks_ok = header_ok and complete and not problem_lines and identity_ok and cp_ok and mp_ok and guards_ok

    if all_checks_ok and verdicts == ["VERDICT READY (stock preflight)"]:
        ready, state, verdict = True, "stock", "VERDICT READY (stock preflight)"
    elif all_checks_ok and verdicts == ["VERDICT READY (open gate applied)"]:
        ready, state, verdict = True, "applied", "VERDICT READY (open gate applied)"
    else:
        ready, state, verdict = False, "not_ready", "VERDICT NOT READY"

    cmd = re.search(r"== file /proc/cmdline\n(.*?)\n== end", text, re.S)
    ver = re.search(r"== file /proc/version\n(.*?)\n== end", text, re.S)

    s3 = {
        "header": head,
        "verdict": verdict,
        "state": state,
        "ready": ready,
        "identity_same": len(same_hashes),
        "identity_differs": identity_differs,
        "coprocessor_sites": sites,
        "libmpr_sites": lm_lines,
        "avcam_stock": av_stock,
        "avcam_target": av_target,
        "avcam_other": av_other,
        "avcam_guards": guard_lines,
        "problem_lines": problem_lines,
        "diagnostic_problem_lines": diag_problems,
        "pages": len(pages),
        "kernel_command_line": cmd.group(1).strip() if cmd else None,
        "kernel_version": ver.group(1).strip() if ver else None,
    }
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_ok": header_ok,
        "euid": "not read",
        "sections": [ln for ln in lines if ln.startswith("== ")],
        "problems": len(problem_lines),
        "complete": complete,
        "s3": s3,
        "_pages": pages,
    }


def check_result(data: bytes) -> dict[str, Any]:
    if CURRENT_WHICH in CURRENT_WRITE_STEPS:
        return parse_write_result(CURRENT_WHICH, CURRENT_WRITE_STEPS[CURRENT_WHICH][2], data)
    return parse_readonly_result(CURRENT_BODY, CURRENT_WHICH, data, CURRENT_EXPECTED)


def has_valid_toolkit_result_header(data: bytes, body_id: str | None = None) -> bool:
    """Return True if data starts with a recognized OpenGate Studio / readcheck header."""
    head = data.split(b"\n", 1)[0].decode("utf8", "replace")
    if head.startswith("readcheck 1 level "):
        return True
    if body_id and body_id in BODY_CONFIG:
        return head.startswith(f"{BODY_CONFIG[body_id]['reader']} ")
    return head.startswith(VALID_READER_PREFIXES)


def known_answer_for(session: Any, camera: Any, kit_dir: Path, manifest: dict[str, Any], cfg: dict[str, str]) -> None:
    with (kit_dir / "DeviceInfo.xml").open("rb") as f:
        want = f.read()
    dev_pin = manifest.get("device_info", {})
    if isinstance(dev_pin, dict) and dev_pin.get("sha256"):
        if c.sha256(want) != dev_pin["sha256"]:
            raise c.StopTest("Kit DeviceInfo.xml SHA-256 mismatch; nothing sent")
    there, data = R.read(camera, R.KNOWN_PATH)
    if not there or data != want:
        detail = (
            "the camera returned no file"
            if not there
            else f"{len(data)} bytes, SHA-256 {c.sha256(data)[:16]}"
        )
        raise c.StopTest(
            f"DeviceInfo.xml is not the file of the {cfg['firmware']} update ({detail}); nothing else is sent"
        )
    session.say(f"Known-answer read: DeviceInfo.xml equals the {cfg['firmware']} file")


def known_answer(session: Any, camera: Any) -> None:
    known_answer_for(session, camera, CURRENT_KIT_DIR, CURRENT_MANIFEST, BODY_CONFIG[CURRENT_BODY])


def run_helper(data: bytes) -> tuple[bytes, str]:
    del data
    if CURRENT_WHICH in CURRENT_WRITE_STEPS:
        lvl = CURRENT_WHICH[1:]
        text = (
            f"readcheck 1 level {lvl}\n"
            "euid 0\n"
            f"== level {lvl}\n"
            "DONE: every site holds the target bytes (canned)\n"
            "== done, bytes written before this line: 0\n"
        )
        return text.encode("utf8"), "canned"
    cfg = BODY_CONFIG[CURRENT_BODY]
    if CURRENT_WHICH == "cineprobe":
        text = (
            f"{cfg['reader']} cineprobe_v1 cineprobe for {cfg['header_model']} {cfg['firmware']}; read-only\n"
            "== file /proc/version\n"
            "Linux (simulated)\n\n"
            "== end 18 bytes\n"
            "== summary\n"
            "VERDICT NOT READY (simulated transport only)\n"
            "== done\n"
        )
        return text.encode("utf8"), "canned"
    label = CURRENT_EXPECTED["label"]
    text = (
        f"{cfg['reader']} {label} {CURRENT_WHICH} for {cfg['header_model']} {cfg['firmware']}; read-only\n"
        "== file /proc/version\n"
        "Linux (simulated)\n\n"
        "== end 18 bytes\n"
        "== summary\n"
        "VERDICT NOT READY (simulated transport only)\n"
        "== done\n"
    )
    return text.encode("utf8"), "canned"


def make_sim(lib: bytes, files: dict[str, bytes] | None = None, fault: str | None = None) -> Any:
    with (CURRENT_KIT_DIR / "DeviceInfo.xml").open("rb") as f:
        dev_info = f.read()

    class Sim(ct1_sim.SimDriver):
        def __init__(self) -> None:
            super().__init__("senser", rules=R.rules(lib))
            self.fs: dict[str, bytes] = {"/usr/share/pmbp/DeviceInfo.xml": dev_info}
            self.fs.update(files or {})
            self.loads = 0
            self.how: str | None = None
            self.dead = False

        def write(self, data: bytes, ep: int = 0) -> Any:
            if self.dead:
                raise ct1_sim.SimUsbError("the simulated camera no longer answers")
            return super().write(data, ep)

        def _handle(self, pfunc: int, body: bytes) -> tuple[int, bytes]:
            import posixpath
            import struct

            try:
                name = c.classify_service_packet(pfunc, body, self.rules)
            except c.GuardRefusal as exc:
                self.unexpected.append(("service packet", pfunc, body[:16].hex(), str(exc)))
                return 0xEE, b""
            st = lambda v: struct.pack("<I", v)
            if name == "SET_FILE_PATH":
                p = body[5:].decode()
                self._path = p if p.startswith("/tmp/jiritsu") else posixpath.normpath("/tmp/jiritsu/" + p)
                return 0, st(R.ST_OK)
            path, self._path = self._path, None
            if path is None:
                return 0, st(0x10000201)
            if name == "GET_FILE2":
                return (0, st(R.ST_OK) + self.fs[path]) if path in self.fs else (0, st(R.ST_NO_FILE))
            if name == "SET_FILE2":
                if body[4:7] != b"\x00\xff\x00":
                    return 0, st(0x10000201)
                if path == R.LIB_PATH.decode() and "/tmp/jbusy" in self.fs:
                    return 0, st(R.ST_BUSY)
                if fault == "dead":
                    self.dead = True
                    self.fs[path] = body[7:]
                    raise ct1_sim.SimUsbError("the simulated camera died during the write")
                self.fs[path] = body[7:]
                if path != R.LIB_PATH.decode():
                    return 0, st(R.ST_OK)
                if fault == "load":
                    return 0, st(R.ST_LOAD_FAILED)
                self.loads += 1
                if "/tmp_wbshd/readcheck_result.txt" not in self.fs:
                    self.fs["/tmp_wbshd/readcheck_result.txt"], self.how = R.run_helper(body[7:])
                return 0, st(R.ST_OK)
            if name == "FILE_DELETE2":
                if fault == "sticky" or path not in self.fs:
                    return 0, st(R.ST_REMOVE_FAILED)
                del self.fs[path]
                return 0, st(R.ST_OK)
            raise AssertionError(name)

    return Sim()


def known_libs() -> dict[str, str]:
    """All toolkit .so SHA-256 hashes (all 3 manifests + superseded studio/upstream hashes + --remove-library)."""
    out: dict[str, str] = dict(EARLIER_LIBS)
    for bid in BODY_CONFIG:
        try:
            _, man = load_body_manifest(bid)
        except OSError:
            continue
        for k, entry in man.get("readonly", {}).items():
            if isinstance(entry, dict) and entry.get("sha256"):
                out[entry["sha256"]] = f"{bid} {k} ({entry['file']})"
        for k, entry in man.get("steps", {}).items():
            if isinstance(entry, dict) and entry.get("sha256"):
                out[entry["sha256"]] = f"{bid} {k} ({entry['file']})"
    out.update(EXTRA_LIBS)
    return out


def use(body_id: str, which: str) -> bytes:
    global CURRENT_BODY, CURRENT_WHICH, CURRENT_KIT_DIR, CURRENT_MANIFEST, CURRENT_EXPECTED, CURRENT_WRITE_STEPS
    kit_dir, manifest = load_body_manifest(body_id)
    expected = load_body_expected(body_id)
    pins, write_steps = step_pins(manifest)
    if which not in pins:
        raise SystemExit(f"{which!r} is not a valid step for {body_id}. Choices: {sorted(pins)}")

    CURRENT_BODY = body_id
    CURRENT_WHICH = which
    CURRENT_KIT_DIR = kit_dir
    CURRENT_MANIFEST = manifest
    CURRENT_EXPECTED = expected
    CURRENT_WRITE_STEPS = write_steps

    name, sha = pins[which]
    lib_path = kit_dir / name
    if not lib_path.is_file():
        raise SystemExit(f"{lib_path} is missing. Nothing was sent.")

    R.LEVEL = step_level(which)
    R.DESIGN = body_id
    R.LIB = lib_path
    R.LIB_SHA256 = sha
    R.KNOWN_LIBS = known_libs()
    R.check_result = check_result
    R.known_answer = known_answer
    R.run_helper = run_helper
    R.make_sim = make_sim
    c.EXPECTED_FIRMWARE = BODY_CONFIG[body_id]["firmware"]
    c.PRIVATE_ROOT = private_root()
    return R.library()


def selftest(lib: bytes) -> list[str]:
    done: list[str] = []

    def check(cond: bool, what: str) -> None:
        if not cond:
            raise AssertionError("self-test failed: " + what)
        done.append(what)

    w_cmd, d_cmd = "SET_FILE2", "FILE_DELETE2"
    s, sim, stopped = R.simulate(lib, R.body_run)
    r = s.results.get("ct6", {})
    check(
        not stopped and not sim.unexpected and R.sent(s).count(w_cmd) == 1 and R.sent(s).count(d_cmd) == 1,
        "normal run: one write, one delete, nothing off the list",
    )
    check(
        R.sent(s).index(d_cmd) < len(R.sent(s)) - 2 and R.sent(s)[-1] == "GET_FILE2",
        "normal run: the delete comes before the result is read",
    )
    check(
        R.LIB_PATH.decode() not in sim.fs and sim.loads == 1,
        "normal run: the library was loaded once and is gone afterwards",
    )
    f = r.get("result", {}).get("s3", {})
    if CURRENT_WHICH in CURRENT_WRITE_STEPS:
        check(bool(f.get("ok")) and bool(r["result"]["header_ok"]), "normal run: the step's result is read as DONE")
    else:
        check(not f.get("ready"), "canned transport result has no measured sites and cannot certify READY")

    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): b"someone else's"})
    check(stopped and w_cmd not in R.sent(s) and d_cmd not in R.sent(s), "foreign libJit.so: stops, nothing written or deleted")
    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): lib})
    check(
        not stopped
        and R.sent(s).count(d_cmd) == 2
        and R.sent(s).count(w_cmd) == 1
        and bool(s.results.get("ct6", {}).get("leftover_removed", {}).get("gone"))
        and R.LIB_PATH.decode() not in sim.fs,
        "leftover known libJit.so: auto-deleted first, then normal run completes",
    )
    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): lib}, fault="sticky")
    check(
        bool(stopped) and w_cmd not in R.sent(s),
        "leftover known libJit.so when delete fails: stops before writing anything",
    )
    s, sim, stopped = R.simulate(lib, R.body_remove_only, files={R.LIB_PATH.decode(): lib})
    check(not stopped and w_cmd not in R.sent(s) and R.LIB_PATH.decode() not in sim.fs, "--remove-only: removes known leftover without writing")
    s, sim, stopped = R.simulate(lib, R.body_remove_only)
    check(not stopped and w_cmd not in R.sent(s) and d_cmd not in R.sent(s), "--remove-only: nothing present sends neither write nor delete")

    foreign_bytes = b"earlier local test build bytes"
    foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()
    EXTRA_LIBS[foreign_sha] = "--remove-library simulation"
    saved_known = R.KNOWN_LIBS
    R.KNOWN_LIBS = known_libs()
    try:
        s, sim, stopped = R.simulate(lib, R.body_remove_only, files={R.LIB_PATH.decode(): foreign_bytes})
        check(
            not stopped
            and w_cmd not in R.sent(s)
            and bool(s.results.get("ct6", {}).get("leftover_removed", {}).get("gone"))
            and R.LIB_PATH.decode() not in sim.fs,
            "--remove-library: removes explicitly listed library cleanly",
        )
    finally:
        EXTRA_LIBS.pop(foreign_sha, None)
        R.KNOWN_LIBS = saved_known
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": b"old"})
    check(stopped and w_cmd not in R.sent(s), "existing result on RAM disk: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp/jbusy": b""})
    check(stopped and w_cmd not in R.sent(s), "/tmp/jbusy present: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/usr/share/pmbp/DeviceInfo.xml": b"<other camera/>"})
    check(stopped and len(R.sent(s)) == 2, "wrong DeviceInfo.xml: stops after known-answer read")
    s, sim, stopped = R.simulate(lib, R.body_run, fault="load")
    check(stopped and R.sent(s).count(d_cmd) == 1 and R.LIB_PATH.decode() not in sim.fs, "load failure: library still deleted")

    saved_req, saved_clr = R.REQUIRE_RESULT_SHA, R.CLEAR_SHA
    try:
        req_bytes = b"authorized preflight result"
        req_sha = hashlib.sha256(req_bytes).hexdigest()
        R.REQUIRE_RESULT_SHA = req_sha
        R.CLEAR_SHA = req_sha

        s, sim, stopped = R.simulate(lib, R.body_run)
        check(bool(stopped) and w_cmd not in R.sent(s), "--require-result: missing result on RAM disk stops before writing")

        s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": b"wrong boot result"})
        check(bool(stopped) and w_cmd not in R.sent(s), "--require-result: mismatched result on RAM disk stops before writing")

        s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": req_bytes})
        check(
            not stopped and R.sent(s).count(d_cmd) == 2 and R.sent(s).count(w_cmd) == 1,
            "--require-result: matching RAM-disk result clears and completes",
        )
    finally:
        R.REQUIRE_RESULT_SHA = saved_req
        R.CLEAR_SHA = saved_clr

    refused = R.refusals(lib)
    check(len(refused) == 15, "guard refuses all 15 forbidden packet classes")

    # Verify single-step Guard still refuses a second file write in one session
    s_dup, _sim_dup, stopped_dup = R.simulate(
        lib,
        lambda _sess, cam, _lib: (
            R.select(cam, R.LIB_PATH),
            R.command(cam, R.SET_FILE2, b"\x00\xff\x00" + lib),
            R.select(cam, R.LIB_PATH),
            R.command(cam, R.SET_FILE2, b"\x00\xff\x00" + lib),
        ),
    )
    check(
        bool(stopped_dup) and "second file write" in stopped_dup and R.sent(s_dup).count(w_cmd) == 1,
        "single-step Guard refuses a second write in one session",
    )

    # Verify MultiStepGuard batch execution & per-step re-arming
    batch_steps = ["check", CURRENT_WHICH] if CURRENT_WHICH != "check" else ["check", "dump"]
    pins, _ = step_pins(CURRENT_MANIFEST)
    batch_libs = {sid: (CURRENT_KIT_DIR / pins[sid][0]).read_bytes() for sid in batch_steps}
    sim_multi = make_sim_multi(
        batch_libs,
        body_id=CURRENT_BODY,
        files={"/tmp_wbshd/readcheck_result.txt": f"{BODY_CONFIG[CURRENT_BODY]['reader']} prior run\n".encode("utf8")},
    )
    seen_callbacks: list[str] = []
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        batch_res = run_batch_single_session(
            CURRENT_BODY,
            batch_steps,
            BODY_CONFIG[CURRENT_BODY]["firmware"],
            writes_memory=True,
            express=True,
            on_step_result=lambda _idx, _tot, sid, _facts, _out: seen_callbacks.append(sid) is None,
            sim_driver=sim_multi,
            settle_seconds=0.0,
        )
    check(
        batch_res["ok"]
        and seen_callbacks == batch_steps
        and sim_multi.loads == len(batch_steps)
        and not sim_multi.unexpected
        and R.LIB_PATH.decode() not in sim_multi.fs,
        "MultiStepGuard batch: clears valid toolkit result, executes all steps sequentially in 1 session",
    )

    # MultiStepGuard must reject writing step B's library while armed for step A
    step_a, step_b = batch_steps[0], batch_steps[1]
    lib_a, lib_b = batch_libs[step_a], batch_libs[step_b]
    if lib_a != lib_b:
        c.use_pmca()
        sess_mm = c.Session("selftest_multiguard_mismatch", write=False, test="CT6")
        sim_mm = make_sim_multi(batch_libs, body_id=CURRENT_BODY)
        mm_stopped = None
        try:
            def _bad_write(cam: Any, guard: MultiStepGuard) -> None:
                guard.arm_step(lib_a, c.sha256(lib_a))
                R.select(cam, R.LIB_PATH)
                R.command(cam, R.SET_FILE2, b"\x00\xff\x00" + lib_b)

            with contextlib.redirect_stdout(io.StringIO()):
                R.service_session_multi(sess_mm, sim_mm, _bad_write)
        except c.StopTest as exc:
            mm_stopped = str(exc)
        check(
            bool(mm_stopped) and sim_mm.loads == 0,
            "MultiStepGuard refuses writing unpinned/other-step library while armed for step A",
        )
    return done


def make_sim_multi(
    libs_by_step: dict[str, bytes],
    *,
    body_id: str = "zve1_202",
    files: dict[str, bytes] | None = None,
    fault: str | None = None,
    result_fn: Any = None,
) -> Any:
    """Create a SimDriver that accepts any step library in libs_by_step for multi-step batch testing."""
    kit_dir, man = load_body_manifest(body_id)
    expected = load_body_expected(body_id)
    cfg = BODY_CONFIG[body_id]
    _, write_steps = step_pins(man)
    dev_info = (kit_dir / "DeviceInfo.xml").read_bytes()
    sha_to_step = {c.sha256(blob): sid for sid, blob in libs_by_step.items()}
    allowed_blobs = set(libs_by_step.values())

    multi_rules = {
        **R.readonly_rules(),
        (c.PFUNC_ADJUST, 0x1001, R.SET_FILE2): (
            "SET_FILE2",
            lambda p: p[:3] == b"\x00\xff\x00" and p[3:] in allowed_blobs,
        ),
    }

    def _default_result(lib_bytes: bytes) -> tuple[bytes, str]:
        if result_fn is not None:
            return result_fn(lib_bytes)
        sid = sha_to_step.get(c.sha256(lib_bytes), "check")
        if sid in write_steps:
            lvl = sid[1:]
            text = (
                f"readcheck 1 level {lvl}\n"
                "euid 0\n"
                f"== level {lvl}\n"
                "DONE: every site holds the target bytes (canned)\n"
                "== done, bytes written before this line: 0\n"
            )
            return text.encode("utf8"), "canned"
        text = (
            f"{cfg['reader']} {expected['label']} {sid} for {cfg['header_model']} {cfg['firmware']}; read-only\n"
            "== file /proc/version\n"
            "Linux (simulated)\n\n"
            "== end 18 bytes\n"
            "== summary\n"
            "VERDICT NOT READY (simulated transport only)\n"
            "== done\n"
        )
        return text.encode("utf8"), "canned"

    class SimMulti(ct1_sim.SimDriver):
        def __init__(self) -> None:
            super().__init__("senser", rules=multi_rules)
            self.fs: dict[str, bytes] = {"/usr/share/pmbp/DeviceInfo.xml": dev_info}
            self.fs.update(files or {})
            self.loads = 0
            self.loaded_steps: list[str] = []
            self.how: str | None = None
            self.dead = False

        def write(self, data: bytes, ep: int = 0) -> Any:
            if self.dead:
                raise ct1_sim.SimUsbError("the simulated camera no longer answers")
            return super().write(data, ep)

        def _handle(self, pfunc: int, body: bytes) -> tuple[int, bytes]:
            try:
                name = c.classify_service_packet(pfunc, body, self.rules)
            except c.GuardRefusal as exc:
                self.unexpected.append(("service packet", pfunc, body[:16].hex(), str(exc)))
                return 0xEE, b""
            st = lambda v: struct.pack("<I", v)
            if name == "SET_FILE_PATH":
                p = body[5:].decode()
                self._path = p if p.startswith("/tmp/jiritsu") else posixpath.normpath("/tmp/jiritsu/" + p)
                return 0, st(R.ST_OK)
            path, self._path = self._path, None
            if path is None:
                return 0, st(0x10000201)
            if name == "GET_FILE2":
                return (0, st(R.ST_OK) + self.fs[path]) if path in self.fs else (0, st(R.ST_NO_FILE))
            if name == "SET_FILE2":
                if body[4:7] != b"\x00\xff\x00":
                    return 0, st(0x10000201)
                if path == R.LIB_PATH.decode() and "/tmp/jbusy" in self.fs:
                    return 0, st(R.ST_BUSY)
                if fault == "dead":
                    self.dead = True
                    self.fs[path] = body[7:]
                    raise ct1_sim.SimUsbError("the simulated camera died during the write")
                self.fs[path] = body[7:]
                if path != R.LIB_PATH.decode():
                    return 0, st(R.ST_OK)
                if fault == "load":
                    return 0, st(R.ST_LOAD_FAILED)
                self.loads += 1
                self.loaded_steps.append(sha_to_step.get(c.sha256(body[7:]), "?"))
                if "/tmp_wbshd/readcheck_result.txt" not in self.fs:
                    self.fs["/tmp_wbshd/readcheck_result.txt"], self.how = _default_result(body[7:])
                return 0, st(R.ST_OK)
            if name == "FILE_DELETE2":
                if fault == "sticky" or path not in self.fs:
                    return 0, st(R.ST_REMOVE_FAILED)
                del self.fs[path]
                return 0, st(R.ST_OK)
            raise AssertionError(name)

    return SimMulti()


def _check_batch_guard_refusals(lib: bytes, sha: str) -> None:
    """Verify MultiStepGuard rules refuse all 15 forbidden packet classes."""
    saved_sha = R.LIB_SHA256
    R.LIB_SHA256 = sha
    try:
        R.refusals(lib)
    finally:
        R.LIB_SHA256 = saved_sha


def run_batch_single_session(
    body_id: str,
    step_ids: list[str],
    firmware: str,
    *,
    writes_memory: bool = True,
    express: bool = True,
    expect_serial_sha256: str | None = None,
    expect_msc_usb_id: str | None = None,
    remove_libraries: list[str] | None = None,
    on_step_start: Any = None,
    on_step_result: Any = None,
    cancel_check: Any = None,
    sim_driver: Any = None,
    connect_fn: Any = None,
    settle_seconds: float = 0.5,
    session_root: Path | None = None,
) -> dict[str, Any]:
    """Execute one or more pinned steps sequentially inside a single MSC->Service Mode USB session."""
    if not step_ids:
        raise ValueError("step_ids must not be empty")
    if body_id not in BODY_CONFIG:
        raise ValueError(f"Unsupported body_id: {body_id!r}")

    cfg = BODY_CONFIG[body_id]
    if firmware != cfg["firmware"]:
        raise SystemExit(
            f"A live run needs --firmware-shown {cfg['firmware']} "
            "(the version shown on the camera's menu). Nothing was sent."
        )

    kit_dir, manifest = load_body_manifest(body_id)
    expected = load_body_expected(body_id)
    pins, write_steps = step_pins(manifest)

    loaded_steps: dict[str, tuple[bytes, str, str]] = {}
    for sid in step_ids:
        if sid not in pins:
            raise ValueError(f"{sid!r} is not a valid step for {body_id}. Choices: {sorted(pins)}")
        if sid in write_steps and not writes_memory:
            raise SystemExit(
                f"{sid} is a write step ({write_steps[sid][2]}). "
                "It needs --writes-memory as well. Nothing was sent."
            )
        fname, want_sha = pins[sid]
        lib_path = kit_dir / fname
        if not lib_path.is_file():
            raise SystemExit(f"{lib_path} is missing. Nothing was sent.")
        lib_bytes = lib_path.read_bytes()
        if c.sha256(lib_bytes) != want_sha or not 0 < len(lib_bytes) <= R.LIB_MAX:
            raise SystemExit(
                f"{lib_path.name} is not the pinned build (SHA-256 {c.sha256(lib_bytes)}, {len(lib_bytes)} bytes). Nothing was sent."
            )
        summary = write_steps[sid][2] if sid in write_steps else str(manifest.get("readonly", {}).get(sid, {}).get("summary") or sid)
        loaded_steps[sid] = (lib_bytes, want_sha, summary)

    for extra in (remove_libraries or []):
        hx = extra.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", hx):
            raise SystemExit(f"Invalid --remove-library SHA-256: {extra!r} (expected 64 hex chars). Nothing was sent.")
        EXTRA_LIBS[hx] = "--remove-library argument"

    # Guard refusal check for every distinct pinned library before touching USB
    checked_shas: set[str] = set()
    for lib_bytes, want_sha, _summary in loaded_steps.values():
        if want_sha not in checked_shas:
            _check_batch_guard_refusals(lib_bytes, want_sha)
            checked_shas.add(want_sha)

    saved_known = R.KNOWN_LIBS
    saved_expected_fw = c.EXPECTED_FIRMWARE
    saved_private = c.PRIVATE_ROOT
    R.KNOWN_LIBS = known_libs()
    c.EXPECTED_FIRMWARE = cfg["firmware"]
    eff_private = session_root if session_root is not None else private_root()
    c.PRIVATE_ROOT = eff_private

    step_results: list[dict[str, Any]] = []
    completed_steps: list[str] = []
    stopped_reason: str | None = None
    cancelled = False
    cancelled_step_index: int | None = None
    cancelled_step_id: str | None = None
    any_left_behind = False
    aborted_by_callback = False

    if sim_driver is not None:
        c.use_pmca()

    stage_name = f"{cfg['prefix']}_{step_ids[0]}" if len(step_ids) == 1 else f"{cfg['prefix']}_express_batch"
    write_session = sim_driver is None or session_root is not None
    ct6_session_name: str | None = None

    try:
        with c.Session(stage_name, write=write_session, test="CT6", root=eff_private) as session:
            if session.dir is not None:
                ct6_session_name = session.dir.name
            session.results.update(
                body_id=body_id,
                firmware_shown_on_camera=firmware,
                model=cfg["model"],
                which=step_ids[0] if len(step_ids) == 1 else "batch",
                steps_planned=list(step_ids),
                express=bool(express),
                library_sha256=loaded_steps[step_ids[0]][1],
                pc={"platform": platform.platform(), "python": sys.version.split()[0]},
            )
            batch_out: dict[str, Any] = {
                "express": bool(express),
                "steps": [],
                "library_sent": False,
                "library_on_camera_after": None,
            }
            session.results["ct6"] = batch_out

            if sim_driver is not None:
                inner = sim_driver
            else:
                import ct1_stage2_service as service

                inner = (connect_fn or service.connect)(session)
                verify_connected_camera_identity(
                    session.results,
                    expect_serial_sha256=expect_serial_sha256,
                    expect_msc_usb_id=expect_msc_usb_id,
                )

            def _clear_result_file(camera: Any, guard: MultiStepGuard, reason_label: str) -> None:
                guard.allow_result_delete = True
                R.select(camera, R.RESULT_PATH)
                del_status, _ = R.command(camera, R.FILE_DELETE2, b"\x00\xff")
                still_there = R.read(camera, R.RESULT_PATH)[0]
                session.say(
                    f"Cleared {reason_label} result file (status {R.text(del_status)}; "
                    f"now {'STILL THERE' if still_there else 'gone'})"
                )
                if still_there:
                    raise c.StopTest(f"could not clear /tmp_wbshd/readcheck_result.txt ({reason_label}); nothing was written.")

            def _run_batch(camera: Any, guard: MultiStepGuard) -> None:
                nonlocal any_left_behind, aborted_by_callback, cancelled, cancelled_step_index, cancelled_step_id
                known_answer_for(session, camera, kit_dir, manifest, cfg)

                there, data = R.read(camera, R.LIB_PATH)
                if there and (R._known_label(c.sha256(data)) is not None or c.sha256(data) in checked_shas):
                    R.remove_leftover(session, camera, batch_out, data)
                    there = False
                if there:
                    sha = c.sha256(data)
                    raise c.StopTest(
                        "a libJit.so is already on the service partition (%d bytes, SHA-256 %s). Nothing was written. "
                        "It is NOT a known library from this toolkit and is left alone. "
                        "If it is an earlier build of ours, pass --remove-library %s."
                        % (len(data), sha, sha)
                    )

                there, old = R.read(camera, R.RESULT_PATH)
                if there:
                    if express and has_valid_toolkit_result_header(old, body_id):
                        session.say(
                            f"Found prior toolkit result on RAM disk ({len(old)} bytes, sha256 {c.sha256(old)[:16]}...); clearing it."
                        )
                        _clear_result_file(camera, guard, "prior express")
                    else:
                        raise c.StopTest(
                            "a result file is already on the RAM disk with an unrecognized header; "
                            "cold boot the camera first. Nothing was written."
                        )

                total = len(step_ids)
                for idx, step_id in enumerate(step_ids, 1):
                    if cancel_check is not None and cancel_check():
                        cancelled = True
                        cancelled_step_index = idx
                        cancelled_step_id = step_id
                        raise c.StopTest(f"Cancelled safely before step {idx} ({step_id}).")

                    if R.read(camera, R.BUSY_PATH)[0]:
                        raise c.StopTest("/tmp/jbusy exists; the camera would refuse the library. Nothing was written.")

                    lib_bytes, sha, summary = loaded_steps[step_id]
                    if on_step_start is not None:
                        on_step_start(idx, total, step_id, summary)

                    step_out: dict[str, Any] = {
                        "step_id": step_id,
                        "step_index": idx,
                        "library_bytes": len(lib_bytes),
                        "library_sha256": sha,
                        "library_sent": False,
                    }
                    batch_out["steps"].append(step_out)

                    guard.arm_step(lib_bytes, sha)
                    try:
                        R.select(camera, R.LIB_PATH)
                        session.say(f"[{idx}/{total}] Sending {step_id} ({len(lib_bytes)} bytes)")
                        step_out["library_sent"] = True
                        batch_out["library_sent"] = True
                        status = None
                        try:
                            status, _ = R.command(camera, R.SET_FILE2, b"\x00\xff\x00" + lib_bytes)
                        except c.GuardRefusal:
                            step_out["library_sent"] = False
                            raise
                        except Exception as exc:
                            step_out["write_error"] = f"{type(exc).__name__}: {exc}"
                            session.say(f"The write got no answer ({step_out['write_error']})")
                        step_out["write_status"] = status
                        if "write_error" not in step_out:
                            session.say(f"[{idx}/{total}] Write and load: status {R.text(status)}")

                        R.remove(session, camera, step_out)
                        batch_out["library_on_camera_after"] = step_out.get("library_on_camera_after")
                        if step_out.get("library_on_camera_after") is True or (
                            step_out.get("library_on_camera_after") is None and step_out.get("library_sent")
                        ):
                            any_left_behind = True
                    finally:
                        guard.disarm_step()

                    if "write_error" in step_out:
                        raise c.StopTest("the write got no answer; the result is not read")

                    there, result = R.read(camera, R.RESULT_PATH)
                    step_out["result_found"] = there
                    if not there:
                        raise c.StopTest(
                            f"no result file after {step_id}: the helper did not create it (status: {R.text(status)})"
                        )

                    res_fname = f"{idx:02d}_{step_id}_readcheck_result.txt" if total > 1 else "readcheck_result.txt"
                    session.save_bytes(res_fname, result)
                    if step_id in write_steps:
                        facts = parse_write_result(step_id, summary, result)
                    else:
                        facts = parse_readonly_result(body_id, step_id, result, expected)
                    step_out["result"] = facts
                    batch_out["result"] = facts

                    pages = facts.pop("_pages", {})
                    facts.pop("_cineprobe_data", None)
                    for addr, (pname, blob) in sorted(pages.items()):
                        prefix = f"{idx:02d}_" if total > 1 else ""
                        session.save_bytes(f"{prefix}cp_{pname}_{addr:08x}.bin", blob)

                    step_entry = {
                        "step_id": step_id,
                        "step_index": idx,
                        "facts": facts,
                        "out": step_out,
                        "sha256": facts.get("sha256"),
                    }
                    step_results.append(step_entry)
                    completed_steps.append(step_id)

                    if on_step_result is not None:
                        keep_going = on_step_result(idx, total, step_id, facts, step_out)
                        if keep_going is False:
                            aborted_by_callback = True
                            break

                    if idx < total:
                        _clear_result_file(camera, guard, f"step {step_id}")

            try:
                R.service_session_multi(session, inner, _run_batch)
            except c.StopTest as exc:
                stopped_reason = str(exc)
                raise
            finally:
                if settle_seconds > 0:
                    time.sleep(settle_seconds)
                if sim_driver is None:
                    c.print_pnp(session, "after the stop request")
    finally:
        R.KNOWN_LIBS = saved_known
        c.EXPECTED_FIRMWARE = saved_expected_fw
        c.PRIVATE_ROOT = saved_private

    ok = (
        not cancelled
        and stopped_reason is None
        and not aborted_by_callback
        and len(completed_steps) == len(step_ids)
    )
    return {
        "ok": ok,
        "body_id": body_id,
        "steps_planned": list(step_ids),
        "steps_run": completed_steps,
        "step_results": step_results,
        "ct6_session": ct6_session_name,
        "camera_usb_identity": session.results.get("camera_usb_identity") or {},
        "library_on_camera_after": any_left_behind,
        "stopped": stopped_reason,
        "cancelled": cancelled,
        "cancelled_step_index": cancelled_step_index,
        "cancelled_step_id": cancelled_step_id,
        "aborted": aborted_by_callback,
    }


def verify_connected_camera_identity(
    session_results: dict[str, Any],
    *,
    expect_serial_sha256: str | None = None,
    expect_msc_usb_id: str | None = None,
) -> None:
    cam_id = session_results.get("camera_usb_identity") or {}
    if expect_serial_sha256:
        got_serial = cam_id.get("serial_sha256")
        if got_serial and got_serial != expect_serial_sha256:
            raise c.StopTest(
                f"Connected camera USB serial ({got_serial[:12]}...) does not match preflight camera "
                f"({expect_serial_sha256[:12]}...). Run fresh preflight. Nothing was sent."
            )
    if expect_msc_usb_id:
        got_msc = cam_id.get("msc_usb_id")
        if got_msc and got_msc != expect_msc_usb_id:
            raise c.StopTest(
                f"Connected camera USB ID ({got_msc}) does not match preflight camera "
                f"({expect_msc_usb_id}). Run fresh preflight. Nothing was sent."
            )


def report(session: Any, facts: dict[str, Any], which: str) -> None:
    cfg = BODY_CONFIG[CURRENT_BODY]
    f = facts["s3"]
    if which in CURRENT_WRITE_STEPS:
        lines = [
            f"{cfg['model']} {cfg['firmware']} step {which}: {f['what']}",
            f"OUTCOME: {f['outcome']}",
            str(f["outcome_line"]),
            *["  " + ln for ln in f["problem_lines"]],
        ]
    elif which == "cineprobe":
        cp = f.get("cineprobe") or {}
        lines = [
            f"{cfg['model']} {cfg['firmware']} cineprobe, {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f["header"],
            f["verdict"],
            f"identity: {f['identity_same']} same, {f['identity_differs']} differ",
            (
                f"cineprobe: {cp.get('dynsym_matches', 0)} syms, "
                f"{cp.get('ro_strings', 0)} strings, "
                f"{cp.get('xrefs', 0)} xrefs, "
                f"{cp.get('xref_ram_blocks', 0)} ram_blocks, "
                f"{cp.get('rw_nonzero_pages', 0)} rw_pages"
            ),
            *(["problem lines:", *["  " + ln for ln in f["problem_lines"]]] if f["problem_lines"] else ["no problem lines"]),
        ]
    else:
        lines = [
            f"{cfg['model']} {cfg['firmware']} {which}, {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f["header"],
            f["verdict"],
            f"identity: {f['identity_same']} same, {f['identity_differs']} differ",
            f"kernel: {f['kernel_version']}",
            f"command line: {f['kernel_command_line']}",
            *[
                f"  coprocessor {s['name']:<16s} {s['address']} len {s['length']:<4d} {s['state']}"
                + ("" if s["shown"] is None else f"  ({s['shown']})")
                for s in f["coprocessor_sites"]
            ],
            *["  " + ln for ln in f["libmpr_sites"]],
            *["  " + ln for ln in f["avcam_guards"]],
            f"  av-cam.bin sites: {f['avcam_stock']} stock, {f['avcam_target']} target, {f['avcam_other']} other",
            *(["problem lines:", *["  " + ln for ln in f["problem_lines"]]] if f["problem_lines"] else ["no problem lines"]),
        ]
    session.save_bytes(cfg["report_name"], ("\n".join(lines) + "\n").encode("utf8"))
    for ln in lines[:8] + (lines[-6:] if len(lines) > 8 else []):
        session.say(ln)


def last_saved_sha() -> str | None:
    root = private_root()
    if not root.is_dir():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
        try:
            with (folder / "manifest.json").open("r", encoding="utf8") as f:
                return json.load(f)["results"]["ct6"]["result"]["sha256"]
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--body", required=True, choices=tuple(BODY_CONFIG))
    ap.add_argument("which", help="check, dump, or a write step id from manifest.json (e.g. V19, H16, B19, I19, P29)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--remove-only", action="store_true")
    ap.add_argument("--clear-result", metavar="SHA256")
    ap.add_argument(
        "--require-result",
        metavar="SHA256",
        help="Require /tmp_wbshd/readcheck_result.txt on the camera to match this SHA-256 (same boot binding) before clearing",
    )
    ap.add_argument("--expect-serial-sha256", metavar="SHA256", help="Optional USB serial SHA-256 binding from preflight")
    ap.add_argument("--expect-msc-usb-id", metavar="VID:PID", help="Optional USB Mass Storage VID:PID binding from preflight")
    ap.add_argument("--firmware-shown")
    ap.add_argument("--writes-memory", action="store_true")
    ap.add_argument("--express", action="store_true", help="Allow clearing prior toolkit result headers and use 0.5s settle")
    ap.add_argument(
        "--remove-library",
        metavar="SHA256",
        action="append",
        default=[],
        help="Also remove an existing /tmp/jiritsu/libJit.so matching this SHA-256 (64 hex chars)",
    )
    args = ap.parse_args(argv)

    if args.require_result:
        req_hx = args.require_result.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", req_hx):
            raise SystemExit(f"Invalid --require-result SHA-256: {args.require_result!r}. Nothing was sent.")
        args.require_result = req_hx
    if args.expect_serial_sha256:
        ser_hx = args.expect_serial_sha256.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", ser_hx):
            raise SystemExit(f"Invalid --expect-serial-sha256: {args.expect_serial_sha256!r}. Nothing was sent.")
        args.expect_serial_sha256 = ser_hx
    if args.expect_msc_usb_id:
        msc_id = args.expect_msc_usb_id.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", msc_id):
            raise SystemExit(f"Invalid --expect-msc-usb-id: {args.expect_msc_usb_id!r}. Nothing was sent.")
        args.expect_msc_usb_id = msc_id

    for extra in args.remove_library:
        hx = extra.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", hx):
            raise SystemExit(f"Invalid --remove-library SHA-256: {extra!r} (expected 64 hex chars). Nothing was sent.")
        EXTRA_LIBS[hx] = "--remove-library argument"

    cfg = BODY_CONFIG[args.body]
    lib = use(args.body, args.which)

    if args.which in CURRENT_WRITE_STEPS and args.go and not (args.dry_run or args.selftest) and not args.writes_memory:
        raise SystemExit(
            f"{args.which} is a write step ({CURRENT_WRITE_STEPS[args.which][2]}). "
            "It needs --writes-memory as well. Use studio_live_apply.py. Nothing was sent."
        )

    if args.dry_run or args.selftest:
        if args.selftest:
            for line in selftest(lib):
                print("PASS  " + line)
            print(f"all checks passed for {args.body} {args.which}; nothing was sent to any device")
        else:
            print("\n".join(R.dry_run_lines(lib)))
        return 0

    if not args.go or args.firmware_shown != cfg["firmware"]:
        raise SystemExit(
            f"A live run needs --go and --firmware-shown {cfg['firmware']} "
            "(the version shown on the camera's menu). Nothing was sent."
        )

    R.refusals(lib)
    selftest(lib)

    is_express = bool(args.express or args.which[0] in ("Q", "F")) and not args.remove_only and not args.require_result
    if is_express:
        res = run_batch_single_session(
            args.body,
            [args.which],
            args.firmware_shown,
            writes_memory=args.writes_memory,
            express=True,
            expect_serial_sha256=args.expect_serial_sha256,
            expect_msc_usb_id=args.expect_msc_usb_id,
            remove_libraries=args.remove_library,
            settle_seconds=0.5,
        )
        if not res["ok"]:
            raise SystemExit(res.get("stopped") or f"Express step {args.which} failed.")
        return 0

    import ct1_stage2_service as service

    if args.require_result:
        R.REQUIRE_RESULT_SHA = args.require_result
        R.CLEAR_SHA = args.require_result
    else:
        R.REQUIRE_RESULT_SHA = None
        R.CLEAR_SHA = args.clear_result or last_saved_sha()
    body_fn = R.body_remove_only if args.remove_only else R.body_run
    stage_name = "remove_only" if args.remove_only else f"{cfg['prefix']}_{args.which}"
    with c.Session(stage_name, test="CT6", root=private_root()) as session:
        session.results.update(
            body_id=args.body,
            firmware_shown_on_camera=args.firmware_shown,
            model=cfg["model"],
            which=args.which,
            library_sha256=R.LIB_SHA256,
            pc={"platform": platform.platform(), "python": sys.version.split()[0]},
        )
        inner = service.connect(session)
        try:
            verify_connected_camera_identity(
                session.results,
                expect_serial_sha256=args.expect_serial_sha256,
                expect_msc_usb_id=args.expect_msc_usb_id,
            )
            R.service_session(session, inner, lambda cam: body_fn(session, cam, lib), lib)
            facts = session.results.get("ct6", {}).get("result")
            if facts and not args.remove_only:
                pages = facts.pop("_pages", {})
                facts.pop("_cineprobe_data", None)
                for addr, (name, blob) in sorted(pages.items()):
                    session.save_bytes(f"cp_{name}_{addr:08x}.bin", blob)
                report(session, facts, args.which)
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            out = session.results.get("ct6", {})
            if isinstance(out.get("leftover_removed"), dict):
                lr = out["leftover_removed"]
                print(
                    f"Leftover /tmp/jiritsu/libJit.so removed first: {lr.get('name')} "
                    f"({lr.get('sha256', '')[:16]}..., gone={lr.get('gone')})."
                )
            after_map = {
                False: "no (confirmed)",
                True: "YES",
                None: "not sent" if not out.get("library_sent") and not args.remove_only else "UNKNOWN",
            }
            print(
                f"Library sent: {'yes' if out.get('library_sent') else 'no'}. "
                f"On the camera now: {after_map[out.get('library_on_camera_after')]}."
            )
            if args.which in CURRENT_WRITE_STEPS:
                print(cfg["power_switch_note"])
            else:
                print(
                    "Nothing on the camera was changed. Unplug and replug the USB cable before another run; "
                    "a cold boot (battery out) clears the result file."
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
