package org.opengatestudio.android

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

private val AmberBg = Color(0xFFFFFBEB)
private val AmberBorder = Color(0xFFF59E0B)
private val AmberInk = Color(0xFF92400E)

private val SafeGreenBg = Color(0xFFECFDF5)
private val SafeGreenInk = Color(0xFF065F46)

private val AlertRedBg = Color(0xFFFEF2F2)
private val AlertRedInk = Color(0xFF991B1B)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    FieldCompanionScreen(
                        onKeepScreenOn = { keepOn ->
                            if (keepOn) {
                                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            } else {
                                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            }
                        }
                    )
                }
            }
        }
    }
}

private enum class CameraBodyOption(val bodyId: String, val label: String, val firmware: String) {
    ZVE1("zve1_202", "ZV-E1", "2.02"),
    A7S3("a7s3_501", "a7S III", "5.01"),
    FX3("fx3_702", "FX3", "7.02")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FieldCompanionScreen(onKeepScreenOn: (Boolean) -> Unit = {}) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val bridge = remember(context) { ChaquopyRuntimeBridge(context) }
    val usbBridge = remember(context) { UsbBridge(context) }

    var selectedBody by remember { mutableStateOf(CameraBodyOption.ZVE1) }
    var offlineMockMode by remember { mutableStateOf(false) }
    var batteryPulled10s by remember { mutableStateOf(false) }
    var inStillsMode by remember { mutableStateOf(false) }
    var confirmFirmwareAndRam by remember { mutableStateOf(false) }

    var bootstrapping by remember { mutableStateOf(true) }
    var pinsVerified by remember { mutableStateOf(false) }
    var checkedFilesCount by remember { mutableIntStateOf(0) }
    var pinErrors by remember { mutableStateOf<List<String>>(emptyList()) }
    var companionState by remember { mutableStateOf<ChaquopyRuntimeBridge.CompanionState?>(null) }

    var isRunning by remember { mutableStateOf(false) }
    var statusHeadline by remember { mutableStateOf("Verifying clean-room payload pins…") }
    var promptTitle by remember { mutableStateOf<String?>(null) }
    var promptDetail by remember { mutableStateOf<String?>(null) }
    var currentStepIndex by remember { mutableIntStateOf(0) }
    var totalStepsCount by remember { mutableIntStateOf(0) }
    var lastRunResult by remember { mutableStateOf<ChaquopyRuntimeBridge.RunResult?>(null) }
    var exportNotice by remember { mutableStateOf<String?>(null) }
    var usbDeviceSummary by remember { mutableStateOf("Scanning USB-OTG…") }
    val eventLog = remember { mutableStateListOf<String>() }

    DisposableEffect(isRunning) {
        onKeepScreenOn(isRunning)
        onDispose { onKeepScreenOn(false) }
    }

    fun refreshUsbSummary() {
        val devs = runCatching { usbBridge.findDevices(UsbBridge.SONY_VID) }.getOrDefault(emptyList())
        usbDeviceSummary = if (devs.isEmpty()) {
            "No Sony USB device detected (VID 0x054C)"
        } else {
            val ids = devs.joinToString(", ") { d ->
                val pid = (d["idProduct"] as? Int) ?: 0
                "054c:%04x".format(pid)
            }
            "${devs.size} Sony USB device(s) detected: $ids"
        }
    }

    suspend fun refreshState() {
        val state = withContext(Dispatchers.IO) {
            bridge.queryState(selectedBody.bodyId, offlineMockMode)
        }
        companionState = state
        pinsVerified = state.pinsVerified
        checkedFilesCount = state.checkedFiles
        pinErrors = state.pinErrors
    }

    suspend fun runBootstrapAndQuery() {
        bootstrapping = true
        statusHeadline = "Unpacking and SHA-256 verifying opengate_kit.zip…"
        val boot = withContext(Dispatchers.IO) { bridge.bootstrapKitFromAssets() }
        pinsVerified = boot.ok
        checkedFilesCount = boot.checkedFiles
        pinErrors = boot.errors
        if (boot.ok) {
            refreshState()
            statusHeadline = "Kit verified (${boot.checkedFiles} files). Ready."
        } else {
            statusHeadline = "Kit verification failed — live USB disabled."
        }
        bootstrapping = false
        refreshUsbSummary()
    }

    LaunchedEffect(Unit) {
        runBootstrapAndQuery()
    }

    LaunchedEffect(selectedBody, offlineMockMode) {
        if (!bootstrapping && pinsVerified) {
            refreshState()
            refreshUsbSummary()
        }
    }

    fun launchAction(action: String, packs: List<String>? = null) {
        if (isRunning) return
        scope.launch {
            isRunning = true
            promptTitle = null
            promptDetail = null
            currentStepIndex = 0
            totalStepsCount = 0
            lastRunResult = null
            exportNotice = null
            eventLog.clear()

            if (!offlineMockMode) {
                OpenGateForegroundService.startSession(
                    context,
                    "Running ${selectedBody.label} $action over USB-OTG…"
                )
            }

            try {
                val res = withContext(Dispatchers.IO) {
                    bridge.executeRun(
                        action = action,
                        bodyId = selectedBody.bodyId,
                        offlineMock = offlineMockMode,
                        usbBridge = usbBridge,
                        firmwareConfirmed = selectedBody.firmware,
                        confirmVolatileRam = confirmFirmwareAndRam,
                        packs = packs
                    ) { ev: JSONObject ->
                        scope.launch(Dispatchers.Main) {
                            when (val kind = ev.optString("type")) {
                                "plan" -> {
                                    val stepsArr = ev.optJSONArray("steps")
                                    totalStepsCount = stepsArr?.length() ?: 1
                                    statusHeadline = "Planned ${totalStepsCount} step(s) for ${selectedBody.label} $action"
                                    eventLog.add("PLAN: $action (${totalStepsCount} steps)")
                                }
                                "wait_drive" -> {
                                    promptTitle = ev.optString("title")
                                    promptDetail = ev.optString("detail")
                                    currentStepIndex = ev.optInt("step_index", currentStepIndex)
                                    val tot = ev.optInt("total_steps", totalStepsCount)
                                    if (tot > 0) totalStepsCount = tot
                                    statusHeadline = promptTitle ?: "Waiting for USB camera…"
                                    if (!offlineMockMode) {
                                        OpenGateForegroundService.updateStatus(context, statusHeadline)
                                    }
                                    eventLog.add("PROMPT: $statusHeadline")
                                }
                                "wait_movie_replug" -> {
                                    promptTitle = ev.optString("title", "Switch camera to Movie mode")
                                    promptDetail = ev.optString("detail")
                                    statusHeadline = promptTitle ?: "Switch to Movie mode and replug USB-C"
                                    if (!offlineMockMode) {
                                        OpenGateForegroundService.updateStatus(context, statusHeadline)
                                    }
                                    eventLog.add("MOVIE REPLUG: $statusHeadline")
                                }
                                "step_start" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    currentStepIndex = ev.optInt("step_index", currentStepIndex)
                                    val tot = ev.optInt("total_steps", totalStepsCount)
                                    if (tot > 0) totalStepsCount = tot
                                    val sid = ev.optString("step_id")
                                    val summary = ev.optString("summary")
                                    statusHeadline = "Step $currentStepIndex/$totalStepsCount: $sid — $summary"
                                    if (!offlineMockMode) {
                                        OpenGateForegroundService.updateStatus(context, statusHeadline)
                                    }
                                    eventLog.add("START $sid: $summary")
                                }
                                "step_done" -> {
                                    val sid = ev.optString("step_id")
                                    val outcome = ev.optString("outcome", "DONE")
                                    eventLog.add("DONE $sid: $outcome")
                                }
                                "closing_dump_start" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    val ck = ev.optString("closing_kind")
                                    statusHeadline = "Running closing verification ($ck)…"
                                    eventLog.add("CLOSING START: $ck")
                                }
                                "closing_dump_done" -> {
                                    val verdict = ev.optString("verdict")
                                    eventLog.add("CLOSING DONE: $verdict")
                                }
                                "complete" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    statusHeadline = ev.optString("verdict", "Completed")
                                    eventLog.add("COMPLETE: $statusHeadline")
                                }
                                "cancelled" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    statusHeadline = ev.optString("message", "Cancelled safely")
                                    eventLog.add("CANCELLED: $statusHeadline")
                                }
                                "error" -> {
                                    val msg = ev.optString("message", "Error")
                                    statusHeadline = msg
                                    eventLog.add("ERROR: $msg")
                                }
                                else -> {
                                    eventLog.add(kind.uppercase())
                                }
                            }
                        }
                    }
                }
                lastRunResult = res
                if (res.ok && res.verdict.isNotEmpty()) {
                    statusHeadline = res.verdict
                } else if (!res.ok && !res.error.isNullOrEmpty()) {
                    statusHeadline = res.error
                }
                refreshState()
                refreshUsbSummary()
            } finally {
                if (!offlineMockMode) {
                    OpenGateForegroundService.stopSession(context)
                }
                isRunning = false
            }
        }
    }

    val decision = companionState?.decision ?: if (!pinsVerified) {
        QuickReapplyDecision.BlockedPinsUnverified
    } else {
        QuickReapplyDecision.RunPreflightThenSafeDailyApply
    }
    val checklistReady = batteryPulled10s && inStillsMode

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("OpenGate Field Companion") }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Pin verification status badge
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (pinsVerified) SafeGreenBg else AlertRedBg
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = if (bootstrapping) {
                            "Verifying Clean-Room Kit Pins…"
                        } else if (pinsVerified) {
                            "Clean-Room Kit Verified ($checkedFilesCount SHA-256 pinned files)"
                        } else {
                            "Kit Verification Failed — Live USB Blocked"
                        },
                        color = if (pinsVerified) SafeGreenInk else AlertRedInk,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.bodyMedium
                    )
                    if (pinErrors.isNotEmpty()) {
                        Text(
                            text = pinErrors.joinToString("\n"),
                            color = AlertRedInk,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }

            // Body selector
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CameraBodyOption.entries.forEach { option ->
                    FilterChip(
                        selected = selectedBody == option,
                        enabled = !isRunning,
                        onClick = {
                            selectedBody = option
                            confirmFirmwareAndRam = false
                            lastRunResult = null
                        },
                        label = { Text("${option.label} ${option.firmware}") }
                    )
                }
            }

            // Mode toggle (Amber Offline Simulation vs Live USB-OTG)
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (offlineMockMode) AmberBg else MaterialTheme.colorScheme.surfaceVariant
                ),
                border = if (offlineMockMode) BorderStroke(1.dp, AmberBorder) else null,
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = if (offlineMockMode) {
                                    "OFFLINE SIMULATION MODE (AMBER)"
                                } else {
                                    "Live USB-OTG Mode (Sony VID 0x054C)"
                                },
                                color = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurface,
                                fontWeight = FontWeight.Bold,
                                style = MaterialTheme.typography.labelLarge
                            )
                            Text(
                                text = if (offlineMockMode) {
                                    "Simulated dry-run only — mock results NEVER unlock live USB apply."
                                } else {
                                    usbDeviceSummary
                                },
                                color = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                        Switch(
                            checked = offlineMockMode,
                            enabled = !isRunning,
                            onCheckedChange = { offlineMockMode = it }
                        )
                    }
                    if (!offlineMockMode) {
                        OutlinedButton(
                            onClick = { refreshUsbSummary() },
                            enabled = !isRunning
                        ) {
                            Text("Refresh USB-OTG Scan")
                        }
                    }
                }
            }

            // Main planner & action card
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Text(
                        text = when (decision) {
                            QuickReapplyDecision.BlockedPinsUnverified ->
                                "Kit Verification Required"
                            QuickReapplyDecision.RunRecoveryPreflightFirst ->
                                "Recovery Check Required"
                            QuickReapplyDecision.RunPreflightThenSafeDailyApply ->
                                if (offlineMockMode) "Ready for Mock Preflight (${selectedBody.label})"
                                else "Ready to Check ${selectedBody.label}"
                            is QuickReapplyDecision.ReadyForSafeDailyApply ->
                                "Verified Clean RAM — Ready for Safe Daily 3:2"
                            QuickReapplyDecision.AlreadyApplied ->
                                "Safe Daily 3:2 Active"
                        },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold
                    )

                    Text(
                        text = "Volatile RAM only — zero flash or SD card writes. Pull camera battery >= 10s anytime to restore stock.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    companionState?.latestSession?.let { sess ->
                        Text(
                            text = "Last session: mode=${sess.mode ?: "?"}, kind=${sess.kind ?: "?"}, state=${sess.state}, ready=${sess.ready}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = batteryPulled10s,
                            enabled = !isRunning,
                            onCheckedChange = { batteryPulled10s = it }
                        )
                        Text("Pulled battery >= 10 seconds (cold RAM baseline)")
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = inStillsMode,
                            enabled = !isRunning,
                            onCheckedChange = { inStillsMode = it }
                        )
                        Text("Camera is in Stills mode (Mass Storage)")
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = confirmFirmwareAndRam,
                            enabled = !isRunning,
                            onCheckedChange = { confirmFirmwareAndRam = it }
                        )
                        Text("Confirm firmware ${selectedBody.firmware} & volatile RAM writes only")
                    }

                    Spacer(modifier = Modifier.height(2.dp))

                    val isApplyPrimary = decision is QuickReapplyDecision.ReadyForSafeDailyApply
                    val primaryLabel = when (decision) {
                        QuickReapplyDecision.BlockedPinsUnverified -> "Re-Verify Payload Integrity"
                        QuickReapplyDecision.RunRecoveryPreflightFirst -> "Run Read-Only Recovery Check"
                        QuickReapplyDecision.RunPreflightThenSafeDailyApply ->
                            if (offlineMockMode) "Run Mock Preflight" else "Check Camera (Read-Only)"
                        is QuickReapplyDecision.ReadyForSafeDailyApply -> "Apply Safe Daily 3:2"
                        QuickReapplyDecision.AlreadyApplied -> "Swapped Battery? Re-Check"
                    }

                    Button(
                        onClick = {
                            when (decision) {
                                QuickReapplyDecision.BlockedPinsUnverified -> {
                                    scope.launch { runBootstrapAndQuery() }
                                }
                                is QuickReapplyDecision.ReadyForSafeDailyApply -> {
                                    launchAction("apply", decision.packs)
                                }
                                else -> {
                                    launchAction("preflight")
                                }
                            }
                        },
                        enabled = !bootstrapping && !isRunning && (
                            decision == QuickReapplyDecision.BlockedPinsUnverified ||
                                (checklistReady && pinsVerified && (!isApplyPrimary || confirmFirmwareAndRam))
                            ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(primaryLabel)
                    }

                    if (offlineMockMode) {
                        val mockReadyForApply = companionState?.latestSession?.let {
                            it.mode == "mock" && it.kind == "preflight" && it.ok && it.ready && it.state == "stock"
                        } == true
                        OutlinedButton(
                            onClick = { launchAction("apply", QuickReapplyPlanner.safeDailyPacks) },
                            enabled = !isRunning && pinsVerified && checklistReady && confirmFirmwareAndRam && mockReadyForApply,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("Simulate Safe Daily 3:2 Apply (Mock Only)")
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedButton(
                            onClick = { launchAction("dump") },
                            enabled = !isRunning && pinsVerified && checklistReady,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("Read-Only Dump")
                        }
                        OutlinedButton(
                            onClick = { launchAction("putback") },
                            enabled = !isRunning && pinsVerified && checklistReady && confirmFirmwareAndRam,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("Put Back Stock")
                        }
                    }

                    if (isRunning) {
                        Button(
                            onClick = { OpenGateForegroundService.requestSafeCancel(context) },
                            colors = ButtonDefaults.buttonColors(containerColor = AlertRedInk),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("Cancel Safely (Between Steps)")
                        }
                    }

                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                val exp = withContext(Dispatchers.IO) { bridge.exportBundle() }
                                if (exp.ok) {
                                    val file = File(exp.zipPath)
                                    val uri = FileProvider.getUriForFile(
                                        context,
                                        "${context.packageName}.fileprovider",
                                        file
                                    )
                                    val shareIntent = Intent(Intent.ACTION_SEND).apply {
                                        type = "application/zip"
                                        putExtra(Intent.EXTRA_STREAM, uri)
                                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                    }
                                    exportNotice = "Exported ${exp.exportedCount} safe file(s); skipped ${exp.skippedPrivate} private file(s)."
                                    context.startActivity(Intent.createChooser(shareIntent, "Share OpenGate Session Bundle"))
                                } else {
                                    exportNotice = "Export failed."
                                }
                            }
                        },
                        enabled = !isRunning,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Export Session Bundle (Excludes Private Dumps)")
                    }

                    exportNotice?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }

            // Live progress / prompt card
            if (isRunning || lastRunResult != null || eventLog.isNotEmpty()) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            text = statusHeadline,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold
                        )
                        if (isRunning) {
                            if (totalStepsCount > 0) {
                                LinearProgressIndicator(
                                    progress = { (currentStepIndex.toFloat() / totalStepsCount.toFloat()).coerceIn(0f, 1f) },
                                    modifier = Modifier.fillMaxWidth()
                                )
                            } else {
                                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                            }
                        }
                        if (promptTitle != null || promptDetail != null) {
                            Card(
                                colors = CardDefaults.cardColors(containerColor = AmberBg),
                                border = BorderStroke(1.dp, AmberBorder),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    promptTitle?.let {
                                        Text(it, color = AmberInk, fontWeight = FontWeight.Bold)
                                    }
                                    promptDetail?.let {
                                        Text(it, color = AmberInk, style = MaterialTheme.typography.bodySmall)
                                    }
                                }
                            }
                        }
                        if (lastRunResult?.leftBehind == true) {
                            Card(
                                colors = CardDefaults.cardColors(containerColor = AlertRedBg),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text(
                                    text = "Helper /tmp/jiritsu/libJit.so may remain on the camera service partition. Pull the camera battery for >= 10 seconds to restore clean stock.",
                                    color = AlertRedInk,
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.padding(12.dp)
                                )
                            }
                        }
                        if (eventLog.isNotEmpty()) {
                            Text(
                                text = eventLog.takeLast(8).joinToString("\n"),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }
    }
}
