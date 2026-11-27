package org.opengatestudio.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    FieldCompanionScreen()
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
fun FieldCompanionScreen() {
    var selectedBody by remember { mutableStateOf(CameraBodyOption.ZVE1) }
    var batteryPulled10s by remember { mutableStateOf(false) }
    var inStillsMode by remember { mutableStateOf(false) }
    var pinsVerified by remember { mutableStateOf(true) }
    var preflightSnapshot by remember { mutableStateOf<SessionSnapshot?>(null) }

    val decision = QuickReapplyPlanner.plan(
        pinsVerified = pinsVerified,
        selectedBodyId = selectedBody.bodyId,
        offlineMockCamera = false,
        preflightResult = preflightSnapshot,
        latestSession = preflightSnapshot,
        resultSource = if (preflightSnapshot != null) "android_usb" else null
    )

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
                .padding(20.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CameraBodyOption.entries.forEach { option ->
                    FilterChip(
                        selected = selectedBody == option,
                        onClick = {
                            selectedBody = option
                            preflightSnapshot = null
                        },
                        label = { Text("${option.label} ${option.firmware}") }
                    )
                }
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text(
                        text = when (decision) {
                            QuickReapplyDecision.BlockedPinsUnverified ->
                                "Kit Verification Required"
                            QuickReapplyDecision.RunRecoveryPreflightFirst ->
                                "Recovery Check Required"
                            QuickReapplyDecision.RunPreflightThenSafeDailyApply ->
                                "Ready to Check ${selectedBody.label}"
                            is QuickReapplyDecision.ReadyForSafeDailyApply ->
                                "Verified Clean RAM — Ready to Apply"
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

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = batteryPulled10s, onCheckedChange = { batteryPulled10s = it })
                        Text("Pulled battery >= 10 seconds (cold RAM baseline)")
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = inStillsMode, onCheckedChange = { inStillsMode = it })
                        Text("Camera is in Stills mode (Mass Storage)")
                    }

                    Spacer(modifier = Modifier.height(4.dp))

                    val primaryLabel = when (decision) {
                        QuickReapplyDecision.BlockedPinsUnverified -> "Verify Payload Integrity"
                        QuickReapplyDecision.RunRecoveryPreflightFirst -> "Run Read-Only Recovery Check"
                        QuickReapplyDecision.RunPreflightThenSafeDailyApply -> "Check Camera (Read-Only)"
                        is QuickReapplyDecision.ReadyForSafeDailyApply -> "Apply Safe Daily 3:2"
                        QuickReapplyDecision.AlreadyApplied -> "Swapped Battery? Re-Check"
                    }

                    Button(
                        onClick = {
                            if (decision == QuickReapplyDecision.RunPreflightThenSafeDailyApply && checklistReady) {
                                // Native Android OTG service invokes opengate_android.runtime over UsbBridge.
                            }
                        },
                        enabled = checklistReady && pinsVerified,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(primaryLabel)
                    }

                    OutlinedButton(
                        onClick = { preflightSnapshot = null },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Export Session Bundle (Excludes Private Dumps)")
                    }
                }
            }
        }
    }
}
