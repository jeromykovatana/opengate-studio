#!/usr/bin/env python3
"""Tests for OpenGate Studio creator workflow: delivery crops, batch card ingest, and relink-verified proxies."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import bionz_clip_check as bcc  # noqa: E402
import studio_creator as sc  # noqa: E402


class CreatorWorkflowTests(unittest.TestCase):
    def test_compute_delivery_crops_3840x2560_and_5760x3840(self) -> None:
        res_4k = sc.compute_delivery_crops(3840, 2560)
        self.assertTrue(res_4k["ok"])
        self.assertEqual(res_4k["source_aspect"], "3:2")
        crops = res_4k["crops"]
        self.assertEqual(set(crops.keys()), {"16:9", "1:1", "9:16", "2.39:1"})

        self.assertEqual((crops["16:9"]["width"], crops["16:9"]["height"]), (3840, 2160))
        self.assertEqual((crops["16:9"]["x"], crops["16:9"]["y"]), (0, 200))
        self.assertEqual((crops["1:1"]["width"], crops["1:1"]["height"]), (2560, 2560))
        self.assertEqual((crops["1:1"]["x"], crops["1:1"]["y"]), (640, 0))
        self.assertEqual((crops["9:16"]["width"], crops["9:16"]["height"]), (1440, 2560))
        self.assertEqual((crops["9:16"]["x"], crops["9:16"]["y"]), (1200, 0))
        self.assertEqual(crops["2.39:1"]["width"], 3840)
        self.assertEqual(crops["2.39:1"]["height"] % 2, 0)
        self.assertAlmostEqual(crops["2.39:1"]["width"] / crops["2.39:1"]["height"], 2.39, delta=0.01)

        for key, crop in crops.items():
            self.assertEqual(crop["width"] % 2, 0, f"{key} width not even")
            self.assertEqual(crop["height"] % 2, 0, f"{key} height not even")
            nr = crop["norm_rect"]
            self.assertGreater(nr["width"], 0.0)
            self.assertLessEqual(nr["width"], 1.0)
            self.assertGreater(nr["height"], 0.0)
            self.assertLessEqual(nr["height"], 1.0)
            self.assertEqual(crop["action_safe"]["scale"], 0.90)
            self.assertEqual(crop["title_safe"]["scale"], 0.80)

        safe = res_4k["safe_areas"]
        self.assertEqual((safe["action_safe_90"]["width"], safe["action_safe_90"]["height"]), (3456, 2304))
        self.assertEqual((safe["title_safe_80"]["width"], safe["title_safe_80"]["height"]), (3072, 2048))

        res_57k = sc.compute_delivery_crops(5760, 3840)
        self.assertEqual((res_57k["crops"]["16:9"]["width"], res_57k["crops"]["16:9"]["height"]), (5760, 3240))
        self.assertEqual((res_57k["crops"]["9:16"]["width"], res_57k["crops"]["9:16"]["height"]), (2160, 3840))

        with self.assertRaises(ValueError):
            sc.compute_delivery_crops(0, 2560)

    def test_ingest_card_batch_sd_tree_with_corrupt_clip_and_appledouble(self) -> None:
        with tempfile.TemporaryDirectory(prefix="og_ingest_") as tmp:
            root = Path(tmp)
            clip_dir = root / "PRIVATE" / "M4ROOT" / "CLIP"
            clip_dir.mkdir(parents=True)

            # Valid 3:2 Open-Gate clip + sidecar
            og_mp4 = clip_dir / "C0001.MP4"
            og_xml = clip_dir / "C0001M01.XML"
            og_mp4.write_bytes(bcc.build_synthetic_mp4(width=3840, height=2560, codec="hvc1"))
            og_xml.write_text(bcc.build_synthetic_xml(width=3840, height=2560, codec="hvc1", aspect_ratio="3:2"), encoding="utf8")

            # AppleDouble macOS resource-fork ghost file that must be skipped
            (clip_dir / "._C0001.MP4").write_bytes(b"\x00\x05\x16\x07junk")

            # Valid Stock 16:9 clip + sidecar
            stock_dir = root / "PRIVATE" / "M4ROOT" / "STOCK"
            stock_dir.mkdir(parents=True)
            st_mp4 = stock_dir / "C0002_stock.MP4"
            st_xml = stock_dir / "C0002_stockM01.XML"
            st_mp4.write_bytes(bcc.build_synthetic_mp4(width=3840, height=2160, codec="hvc1"))
            st_xml.write_text(bcc.build_synthetic_xml(width=3840, height=2160, codec="hvc1", aspect_ratio="16:9"), encoding="utf8")

            # Corrupt clip that must NOT abort the batch
            bad_mp4 = clip_dir / "C0003_corrupt.MP4"
            bad_mp4.write_bytes(b"not-a-valid-mp4")

            res = sc.ingest_card_batch(root, expect="auto", recursive=True)
            self.assertTrue(res["ok"])
            self.assertFalse(res["all_clips_ok"])
            self.assertEqual(res["clips_scanned"], 3)
            self.assertEqual(res["clips_passed"], 2)
            self.assertEqual(res["clips_failed"], 1)

            by_name = {c["filename"]: c for c in res["clips"]}
            self.assertNotIn("._C0001.MP4", by_name)
            self.assertTrue(by_name["C0001.MP4"]["ok"])
            self.assertEqual(by_name["C0001.MP4"]["expected_mode"], "open-gate")
            self.assertIsNotNone(by_name["C0001.MP4"]["sidecar_xml"])
            self.assertIsNotNone(by_name["C0001.MP4"]["delivery_crops"])

            self.assertTrue(by_name["C0002_stock.MP4"]["ok"])
            self.assertEqual(by_name["C0002_stock.MP4"]["expected_mode"], "stock")

            self.assertFalse(by_name["C0003_corrupt.MP4"]["ok"])
            self.assertTrue(by_name["C0003_corrupt.MP4"]["issues"])

            # Non-recursive at card root finds 0 top-level MP4s
            non_rec = sc.ingest_card_batch(root, expect="auto", recursive=False)
            self.assertEqual(non_rec["clips_scanned"], 0)

    def test_generate_proxies_real_ffmpeg_and_relink_verification(self) -> None:
        ffmpeg_bin = sc._find_media_tool("ffmpeg")
        with tempfile.TemporaryDirectory(prefix="og_proxy_") as tmp:
            root = Path(tmp)
            src_mp4 = root / "C0010.MP4"
            src_xml = root / "C0010M01.XML"
            src_xml.write_text(bcc.build_synthetic_xml(width=3840, height=2560, codec="hvc1", aspect_ratio="3:2"), encoding="utf8")

            # Generate a tiny real 3:2 H.264 MP4 (384x256, 24000/1001 fps, stereo audio, timecode)
            gen_cmd = [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=384x256:rate=24000/1001:duration=0.6",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=0.6",
                "-ac",
                "2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-timecode",
                "01:23:45:00",
                str(src_mp4),
            ]
            proc = subprocess.run(gen_cmd, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, f"Failed to synthesize fixture MP4: {proc.stderr}")

            # 1. Dry-run must not write files
            dry_dir = root / "proxies_dry"
            dry_res = sc.generate_proxies(
                inputs=[src_mp4],
                out_dir=dry_dir,
                aspect="3:2",
                resolution="720p",
                codec="h264",
                dry_run=True,
            )
            self.assertTrue(dry_res["ok"])
            self.assertTrue(dry_res["dry_run"])
            self.assertFalse(dry_dir.exists())
            self.assertEqual(dry_res["target_width"], 1080)
            self.assertEqual(dry_res["target_height"], 720)
            self.assertTrue(dry_res["proxies"][0]["relink_to_original_for_gyro"])
            self.assertFalse(dry_res["proxies"][0]["rtmd_preserved_in_proxy"])

            # 2. Real 3:2 720p H.264 proxy with sidecar & relink verification
            out_3x2 = root / "proxies_3x2"
            res_3x2 = sc.generate_proxies(
                inputs=[src_mp4],
                out_dir=out_3x2,
                aspect="3:2",
                resolution="720p",
                codec="h264",
                preserve_gyro_sidecar=True,
                dry_run=False,
            )
            self.assertTrue(res_3x2["ok"], f"3:2 proxy generation failed: {res_3x2}")
            self.assertEqual(res_3x2["succeeded_count"], 1)
            self.assertTrue((out_3x2 / "proxy_manifest.json").is_file())
            manifest_data = json.loads((out_3x2 / "proxy_manifest.json").read_text(encoding="utf8"))
            self.assertEqual(manifest_data["succeeded_count"], 1)

            item = res_3x2["proxies"][0]
            self.assertTrue(item["ok"])
            self.assertTrue(Path(item["output_file"]).is_file())
            self.assertTrue(item["sidecar_copied"])
            self.assertTrue(Path(item["sidecar_output"]).is_file())
            self.assertFalse(item["rtmd_preserved_in_proxy"])
            self.assertTrue(item["relink_to_original_for_gyro"])

            rv = item["relink_verification"]
            self.assertTrue(rv["fps_match"])
            self.assertLessEqual(rv["duration_delta_sec"], 0.15)
            self.assertTrue(rv["timecode_match"])
            self.assertTrue(rv["audio_channels_match"])
            self.assertTrue(rv["original_sha256_unchanged"])
            self.assertTrue(rv["relink_ok"])

            # 3. Cropped 16:9 proxy must NOT copy 3:2 M01.XML sidecar
            out_16x9 = root / "proxies_16x9"
            res_16x9 = sc.generate_proxies(
                inputs=[src_mp4],
                out_dir=out_16x9,
                aspect="16:9",
                resolution="720p",
                codec="h264",
                preserve_gyro_sidecar=True,
                dry_run=False,
            )
            self.assertTrue(res_16x9["ok"], f"16:9 proxy generation failed: {res_16x9}")
            item_16x9 = res_16x9["proxies"][0]
            self.assertEqual((item_16x9["target_width"], item_16x9["target_height"]), (1280, 720))
            self.assertFalse(item_16x9["sidecar_copied"])
            self.assertIsNotNone(item_16x9["sidecar_note"])
            self.assertTrue(item_16x9["relink_verification"]["relink_ok"])

            # 4. ProRes .mov 3:2 proxy
            out_prores = root / "proxies_prores"
            res_prores = sc.generate_proxies(
                inputs=[src_mp4],
                out_dir=out_prores,
                aspect="3:2",
                resolution="720p",
                codec="prores",
                preserve_gyro_sidecar=False,
                dry_run=False,
            )
            self.assertTrue(res_prores["ok"], f"ProRes proxy generation failed: {res_prores}")
            item_pr = res_prores["proxies"][0]
            self.assertTrue(item_pr["output_file"].endswith(".mov"))
            self.assertFalse(item_pr["sidecar_copied"])
            self.assertTrue(item_pr["relink_verification"]["relink_ok"])

    def test_studio_cli_creator_and_gyro_subcommands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="og_cli_creator_") as tmp:
            root = Path(tmp)
            clip_dir = root / "PRIVATE" / "M4ROOT" / "CLIP"
            clip_dir.mkdir(parents=True)
            mp4 = clip_dir / "C0001.MP4"
            xml = clip_dir / "C0001M01.XML"
            mp4.write_bytes(bcc.build_synthetic_mp4(width=3840, height=2560, codec="hvc1"))
            xml.write_text(bcc.build_synthetic_xml(width=3840, height=2560, codec="hvc1", aspect_ratio="3:2"), encoding="utf8")

            cli_path = REPO_ROOT / "cli" / "studio_cli.py"

            diag_proc = subprocess.run(
                [sys.executable, str(cli_path), "gyro-diagnose", str(mp4), "--body", "zve1_202", "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(diag_proc.returncode, 0, diag_proc.stderr)
            diag_data = json.loads(diag_proc.stdout)
            self.assertTrue(diag_data["ready_for_gyroflow"])
            self.assertEqual(diag_data["failure_category"], "none")
            self.assertEqual(diag_data["readout_calibration"]["evidence_level"], "estimated_from_imx510_line_ratio")

            list_proc = subprocess.run(
                [sys.executable, str(cli_path), "install-gyroflow-presets", "--list-only", "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
            list_data = json.loads(list_proc.stdout)
            self.assertTrue(list_data["ok"])
            self.assertEqual(len(list_data["presets"]), 4)

            inst_dir = root / "gyroflow_installed"
            inst_proc = subprocess.run(
                [sys.executable, str(cli_path), "install-gyroflow-presets", "--target-dir", str(inst_dir), "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(inst_proc.returncode, 0, inst_proc.stderr)
            inst_data = json.loads(inst_proc.stdout)
            self.assertTrue(inst_data["ok"])
            self.assertEqual(inst_data["installed_count"], 4)

            ingest_proc = subprocess.run(
                [sys.executable, str(cli_path), "ingest-batch", str(root), "--body", "zve1_202", "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(ingest_proc.returncode, 0, ingest_proc.stderr)
            ingest_data = json.loads(ingest_proc.stdout)
            self.assertTrue(ingest_data["ok"])
            self.assertEqual(ingest_data["clips_scanned"], 1)
            self.assertEqual(ingest_data["gyroflow_ready_count"], 1)


if __name__ == "__main__":
    unittest.main()
