#!/usr/bin/env python3
"""Unit tests for rtmd cadence/KLV inspection, gyro diagnostics, and Gyroflow presets."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import bionz_clip_check as bcc  # noqa: E402
import studio_gyro as sg  # noqa: E402


class RtmdValidationTests(unittest.TestCase):
    def test_valid_rtmd_cadence_stsz_and_klv_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mp4 = root / "C0001.MP4"
            xml = root / "C0001M01.XML"
            xml_txt = bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p", aspect_ratio="3:2")
            mp4.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001,
                    frame_count=24, rtmd_samples=24, rtmd_sample_bytes=512,
                    embedded_xml=xml_txt,
                )
            )
            xml.write_text(xml_txt, encoding="utf8")

            rep, _ = bcc.inspect_clip(mp4, xml_path=xml, body="zve1")
            self.assertTrue(rep["ok"], rep)
            self.assertEqual(rep["rtmd_timescale"], 24000)
            self.assertTrue(rep["rtmd_cadence_constant"])
            self.assertEqual(rep["rtmd_fps"], "23.976p")
            self.assertEqual(rep["rtmd_duration_sec"], 1.0)
            self.assertLessEqual(rep["rtmd_timestamp_drift_ms"], 1.0)
            self.assertEqual(rep["rtmd_min_sample_bytes"], 512)
            self.assertEqual(rep["rtmd_max_sample_bytes"], 512)
            self.assertEqual(rep["rtmd_zero_size_samples"], 0)
            self.assertTrue(rep["rtmd_payload_readable"])
            self.assertTrue(rep["rtmd_klv_detected"])

    def test_rtmd_drift_variable_cadence_zero_size_and_corrupt_klv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # 1. Timestamp drift (>100ms)
            p_drift = root / "drift.MP4"
            p_drift.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001,
                    rtmd_drift_ms=250.0,
                )
            )
            rep_drift, _ = bcc.inspect_clip(p_drift, body="fx3")
            self.assertFalse(rep_drift["ok"])
            self.assertGreater(rep_drift["rtmd_timestamp_drift_ms"], 200.0)
            self.assertTrue(any("drifts" in i for i in rep_drift["issues"]))

            # 2. Variable rtmd stts cadence
            p_var = root / "varcad.MP4"
            p_var.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001,
                    rtmd_variable_cadence=True,
                )
            )
            rep_var, _ = bcc.inspect_clip(p_var, body="fx3")
            self.assertFalse(rep_var["rtmd_cadence_constant"])
            self.assertTrue(any("Variable rtmd" in w for w in rep_var["warnings"]))

            # 3. Zero-size samples in stsz
            p_zero = root / "zerosz.MP4"
            p_zero.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001,
                    rtmd_zero_size_samples=3,
                )
            )
            rep_zero, _ = bcc.inspect_clip(p_zero, body="s3")
            self.assertFalse(rep_zero["ok"])
            self.assertEqual(rep_zero["rtmd_zero_size_samples"], 3)
            self.assertEqual(rep_zero["rtmd_min_sample_bytes"], 0)
            self.assertEqual(rep_zero["rtmd_max_sample_bytes"], 512)

            # 4. Corrupt KLV payload in mdat
            p_corrupt = root / "corrupt.MP4"
            p_corrupt.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001,
                    corrupt_rtmd=True,
                )
            )
            rep_corrupt, _ = bcc.inspect_clip(p_corrupt, body="zve1")
            self.assertFalse(rep_corrupt["ok"])
            self.assertTrue(rep_corrupt["rtmd_payload_readable"])
            self.assertFalse(rep_corrupt["rtmd_klv_detected"])

            # 5. Unreadable stco offsets outside mdat
            p_bad_stco = root / "badstco.MP4"
            p_bad_stco.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001,
                    rtmd_bad_stco=True,
                )
            )
            rep_bad_stco, _ = bcc.inspect_clip(p_bad_stco, body="zve1")
            self.assertFalse(rep_bad_stco["ok"])
            self.assertFalse(rep_bad_stco["rtmd_payload_readable"])
            self.assertFalse(rep_bad_stco["rtmd_klv_detected"])


class GyroDiagnosticTests(unittest.TestCase):
    def test_failure_categories_and_readout_honesty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # 1. Healthy clip -> failure_category == "none"
            p_ok = root / "ok.MP4"
            x_ok = root / "okM01.XML"
            xml_ok = bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p", aspect_ratio="3:2")
            p_ok.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, embedded_xml=xml_ok))
            x_ok.write_text(xml_ok, encoding="utf8")

            d_ok = sg.diagnose_clip_gyro(p_ok, xml_path=x_ok, body="zve1")
            self.assertTrue(d_ok["ok"])
            self.assertTrue(d_ok["ready_for_gyroflow"])
            self.assertTrue(d_ok["ready_for_catalyst"])
            self.assertEqual(d_ok["body_id"], "zve1_202")
            self.assertEqual(d_ok["failure_category"], "none")
            self.assertEqual(d_ok["readout_calibration"]["frame_readout_time_ms"], 12.336)
            self.assertEqual(d_ok["readout_calibration"]["evidence_level"], "hardware_measured")
            self.assertIn("OFF", d_ok["ibis_guidance"]["active_steadyshot_warning"])

            # 2. crop_geometry: 16:9 XML or 2160 VPRF mismatch
            p_crop = root / "crop.MP4"
            x_crop = root / "cropM01.XML"
            p_crop.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001))
            x_crop.write_text(bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p", aspect_ratio="16:9"), encoding="utf8")
            d_crop = sg.diagnose_clip_gyro(p_crop, xml_path=x_crop, body="fx3")
            self.assertFalse(d_crop["ok"])
            self.assertFalse(d_crop["ready_for_gyroflow"])
            self.assertEqual(d_crop["failure_category"], "crop_geometry")

            # 3. metadata: stripped rtmd or corrupt KLV
            p_meta = root / "meta.MP4"
            p_meta.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, include_rtmd=False))
            d_meta = sg.diagnose_clip_gyro(p_meta, body="s3")
            self.assertFalse(d_meta["ok"])
            self.assertEqual(d_meta["failure_category"], "metadata")

            # 4. rtmd_cadence: drift > 100ms
            p_cad = root / "cad.MP4"
            p_cad.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, rtmd_drift_ms=300.0))
            d_cad = sg.diagnose_clip_gyro(p_cad, body="zve1")
            self.assertFalse(d_cad["ok"])
            self.assertEqual(d_cad["failure_category"], "rtmd_cadence")

            # 5. lens_profile: manual 0mm lens in XML or unknown body
            p_lens = root / "lens.MP4"
            x_lens = root / "lensM01.XML"
            p_lens.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001))
            x_lens.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">\n'
                '  <VideoFormat>\n'
                '    <VideoFrame videoCodec="HEVC_3840_2560_H420P@L51" captureFps="23.976p" formatFps="23.976p"/>\n'
                '    <VideoLayout pixel="3840" numOfVerticalLine="2560" aspectRatio="3:2"/>\n'
                '  </VideoFormat>\n'
                '  <Device manufacturer="Sony" modelName="ZV-E1" serialNo="4294967295"/>\n'
                '  <Lens modelName="Manual" focalLength="0"/>\n'
                '</NonRealTimeMeta>\n',
                encoding="utf8",
            )
            d_lens = sg.diagnose_clip_gyro(p_lens, xml_path=x_lens, body="fx3")
            self.assertFalse(d_lens["ok"])
            self.assertEqual(d_lens["failure_category"], "lens_profile")

            d_unk = sg.diagnose_clip_gyro(p_ok, xml_path=x_ok, body="unknown_cam")
            self.assertFalse(d_unk["ok"])
            self.assertEqual(d_unk["failure_category"], "lens_profile")

            # 6. app_compatibility: Active SteadyShot in XML
            p_app = root / "app.MP4"
            x_app = root / "appM01.XML"
            p_app.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001))
            x_app.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">\n'
                '  <VideoFormat>\n'
                '    <VideoFrame videoCodec="HEVC_3840_2560_H420P@L51" captureFps="23.976p" formatFps="23.976p"/>\n'
                '    <VideoLayout pixel="3840" numOfVerticalLine="2560" aspectRatio="3:2"/>\n'
                '  </VideoFormat>\n'
                '  <Device manufacturer="Sony" modelName="ZV-E1" serialNo="4294967295"/>\n'
                '  <SteadyShot mode="Active"/>\n'
                '</NonRealTimeMeta>\n',
                encoding="utf8",
            )
            d_app = sg.diagnose_clip_gyro(p_app, xml_path=x_app, body="zve1")
            self.assertFalse(d_app["ok"])
            self.assertFalse(d_app["ready_for_gyroflow"])
            self.assertFalse(d_app["ready_for_catalyst"])
            self.assertEqual(d_app["failure_category"], "app_compatibility")
            self.assertTrue(d_app["ibis_guidance"]["active_steadyshot_detected"])


class GyroflowPresetTests(unittest.TestCase):
    def test_presets_valid_json_honest_evidence_and_install_tempdir(self) -> None:
        listing = sg.list_gyroflow_presets()
        self.assertTrue(listing["ok"], listing)
        presets = listing["presets"]
        self.assertEqual(len(presets), 4)
        body_ids = {p["body_id"] for p in presets}
        self.assertEqual(body_ids, {"zve1_202", "a7s3_501", "fx3_702", "a7iv_602"})

        for p in presets:
            fpath = Path(listing["preset_dir"]) / p["filename"]
            self.assertTrue(fpath.is_file())
            data = json.loads(fpath.read_text(encoding="utf8"))
            self.assertEqual(data["camera_brand"], "Sony")
            self.assertEqual(data["camera_model"], p["camera_model"])
            dim = f"{data['calib_dimension']['w']}x{data['calib_dimension']['h']}"
            self.assertEqual(dim, p["dimension"])
            self.assertEqual(float(data["frame_readout_time"]), p["frame_readout_time_ms"])
            self.assertEqual(data["num_images"], 0)
            self.assertFalse(data["official"])
            if p["body_id"] == "zve1_202":
                self.assertEqual(p["evidence_level"], "hardware_measured")
                self.assertAlmostEqual(p["frame_readout_time_ms"], 12.336, places=3)
            elif p["body_id"] == "a7iv_602":
                self.assertEqual(p["evidence_level"], "estimated_from_imx710_line_ratio")
            else:
                self.assertEqual(p["evidence_level"], "estimated_from_imx510_line_ratio")
                self.assertAlmostEqual(p["frame_readout_time_ms"], 10.3, places=2)
            self.assertEqual(len(p["sha256"]), 64)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "Gyroflow" / "lens_profiles" / "OpenGateStudio"
            res_all = sg.install_gyroflow_presets(target_dir=dest)
            self.assertTrue(res_all["ok"])
            self.assertEqual(res_all["installed_count"], 4)
            for f in res_all["installed_files"]:
                self.assertTrue(Path(f).is_file())

            dest_one = Path(tmp) / "single"
            res_one = sg.install_gyroflow_presets(target_dir=dest_one, body_id="fx3")
            self.assertTrue(res_one["ok"])
            self.assertEqual(res_one["installed_count"], 1)
            self.assertTrue(res_one["installed_files"][0].endswith("Sony_ILME-FX3_OpenGate_3840x2560_3x2.json"))

            res_bad = sg.install_gyroflow_presets(target_dir=dest_one, body_id="nonexistent_body")
            self.assertFalse(res_bad["ok"])
            self.assertEqual(res_bad["installed_count"], 0)


if __name__ == "__main__":
    unittest.main()
