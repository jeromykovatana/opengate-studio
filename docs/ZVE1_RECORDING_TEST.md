# ZV-E1 2.02 · 3:2 metadata and gyro test

**What is ready.** The existing native metadata design matches build `32000_08.2025101101`. Its eight required sites, one optional site and 17 guards passed offline checks. The current ZV-E1 field kit uses the earlier recorder design. Use it only for the baseline in this comparison. An unmerged desktop build now covers the MP4 height fields. Its scope and outstanding checks are recorded below. The desktop clip checker and geometry-only control copy work independently of that integration. [Native design](designs/mp4_3x2_zv_202.json) · [Build verification and live approval requirements](OFFSET_AUDIT.md) · [Clip checker](../tools/zve1_clip_check.py)

## Set up once

- Confirm the body menu shows **ZV-E1 2.02**. Use normal Movie mode, NTSC, **XAVC HS 4K, 24p (23.976), 50M 4:2:0 10-bit**, full frame. Disable S&Q, APS-C, proxies, auto framing and electronic zoom. Keep the same card, codec and rate throughout. This matches the reported ZV-E1 open-gate capture.
- Shoot landscape. Use a lens that communicates focal length to the camera, preferably a Sony prime or a zoom fixed at about 24 mm. Turn camera SteadyShot and lens OSS off for all takes. Leave audio on, lock focus, exposure and white balance, and use steady daylight with a shutter around 1/125 s.
- On a wall, mark the centre and left/right edges. Put a circular target near the centre and put tape just above and below the stock frame. Mark the tripod feet, head angle and focal length so each framing take starts from the same position.
- Copy each pair into its own folder before changing states. Keep the camera filenames and the matching Sony XML sidecars together. Keep the original card files untouched. Note body firmware, kit revision/state, lens, focal length, stabilization settings, clip IDs and any purple standby or playback issue.

## Six short clips

**C1/C2 build status.** An offline comparison of the ZV-E1 2.02 recorder design shipped in the test kit against the native metadata design found **0 of 8 required changes active**. Two appear in the baseline's optional list. All eight required locations and all 17 guard blocks matched the local firmware image. This verifies the design's input build. Keep recordings from the current launcher labeled B even if a host-side control copy imports correctly.

**Upstream candidate checked November 24, 2026.** Open PR #2, head `ff1a5ff56b217dd797b1c960c6d7c009162bc540`, contains a desktop build for firmware 2.02. Offline inspection found that its design retains the baseline entries and activates the two AVC/HEVC MP4 header changes. Their expected bytes matched the pinned local recorder library. Both bundled AArch64 helper binaries matched the SHA-256 values in the PR runner. This verifies package consistency. The contributor used a different compiler from the maintainer and requested a maintainer rebuild. The Android APK is identical to the local baseline. [Upstream PR and tester report](https://github.com/ArcaneLantern/zve1-open-gate-test/pull/2)

The contributor reports native 3840×2560 HEVC, track, sample-entry and VPRF dimensions at 23.98p. Embedded and sidecar Sony XML still report 3840×2160. For this revision a correct geometry result and an XML mismatch can coexist. Record both and retain the checker's original-file verdict. The revision contains no original camera clip for independent gyro or editor testing. The author also reports that the read-only preflight omits the two new header sites and can report READY after a power-switch cycle leaves the camera in a mixed state with black rows. Keep the C1/C2 trial on hold under the existing preflight requirement. The tape marks in C1 distinguish added image area from padded rows.

**Local desktop preflight update.** Commit `6656c64` on `review/zve1-preflight` adds both MP4 header reads. A host build of the verdict code and desktop report tests rejected a stock sensor with an applied encoder, as well as either header applied alone. Both read-only binaries match their new SHA-256 pins. The patch applies to the PR head above. A maintainer update to the PR and an on-camera read-only result are still pending. [Verified PR patch](zve1-pr2-readonly-preflight.patch)

| State | Framing take | Gyro take |
| --- | --- | --- |
| A · Stock | A1. Record the wall for **10 seconds** on the locked tripod. | A2. Record the handheld movement below for **20 seconds**. This confirms the lens and recording settings produce usable gyro data. |
| B · Existing 3:2 baseline | B1. Return to the marked tripod position. Record **10 seconds**. The upper and lower tape should enter the frame while the left and right marks stay in place. | B2. Repeat the **20-second** movement. This clip also supplies the optional desktop control copy. |
| C · Native metadata fix | C1. Once an integrated build is available for this body, repeat B1 for **10 seconds**. | C2. Repeat B2 for **20 seconds**. Play C1 and C2 back on the camera and note whether they open and display correctly. |

For each gyro take, aim at a detailed scene with a vertical doorframe. Hold still for 3 seconds, slowly pan right and back for 8 seconds, then make two gentle wrist rolls for 6 seconds and hold still for the last 3 seconds. The two movement axes and still intervals make motion and timing easy to recognize. Keep the doorframe visible.

Transitions into B and C are separate camera sessions. Any live USB or administrator command requires explicit approval. The exact-build read-only check must report READY before a write test. C also requires coverage of the new metadata sites in that build’s preflight. For now A1/A2 can be recorded with normal camera controls. Keep B and C at 24p, and end the trial if the camera restarts or produces an incomplete clip.

## Inspect the card originals offline

From the workspace root, substitute the actual clip and matching sidecar names. Use the first command on A1/A2 and the second on B1/B2 and C1/C2.

```sh
python3 tools/zve1_clip_check.py 'A/C0001.MP4' --expect stock --xml 'A/C0001M01.XML'
python3 tools/zve1_clip_check.py 'C/C0005.MP4' --expect open-gate --xml 'C/C0005M01.XML'
```

The report shows video track and HEVC sample-entry dimensions, the first decoded HEVC pictures independently of the container, pixel aspect, frame rate, timed-metadata packet count and a digest of packet payloads and timestamps. It reads the sidecar’s VideoLayout and reported codec size. Exit 0 means the file checks passed, exit 1 identifies an unmet or missing original-file check, and exit 2 indicates an inspection error. A sidecar may omit the aspect flag when its dimensions are correct.

**Optional matched control.** If B2 contains 3840×2560 pictures but both MP4 headers still say 3840×2160, create a separate local MP4 with only those two height fields corrected. Use an existing local folder for the output, away from the original card folder. The checker verifies the corrected file and the original have identical timed-metadata packet payloads and timestamps before publishing it. It leaves the original XML in place. The exit status still describes the B2 original, so 1 is expected for this comparison.

```sh
python3 tools/zve1_clip_check.py 'B/C0004.MP4' --expect open-gate --xml 'B/C0004M01.XML' --control-copy 'B2-control.MP4'
```

## What counts as success

1. **Framing.** A1 reads 3840×2160. B1 and C1 decode to 3840×2560. C1’s MP4 track, HEVC sample entry and sidecar agree with the decoded picture at square pixels. In Resolve, use original media and a 3840×2560 timeline with automatic clip attributes. Confirm the circle is round, both extra marks appear, and horizontal coverage matches A1. Inspect the source dimensions as well as the timeline viewer.
2. **Gyro.** Open A2 in Gyroflow or Catalyst and verify that the application can use the clip’s embedded motion data. Repeat on C2 using only the original MP4 for telemetry. In Gyroflow, inspect the motion trace for still intervals, the pan and the rolls. Compare stabilization on and off over the same section at comparable zoom. Save the application version, lens profile/crop, and a screenshot or short comparison. Look for reduced unwanted roll with no drift, warping or lag. Check B2 and its optional control for diagnosis. A matching control digest proves preservation on that same take. Different takes naturally have different digests.
3. **Diagnosis.** If A2 has no usable gyro, resolve the stock lens/settings/application combination first. If decoded video is tall and the MP4 is wide, the container is still wrong. If MP4 geometry passes but XML is stale, track that independently. If geometry and packet checks pass but stabilization fails, keep gyro compatibility open and record whether the application lacked a matching lens profile, failed to read telemetry, or stabilized incorrectly.

Offline self-checks used synthetic HEVC movies with tagged test packets. They exercised the parser, incorrect headers, sidecar mismatch and copy preservation. Sony motion samples and application playback still require the recordings above.
