package com.mobilestore.scanner.ui

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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mobilestore.scanner.network.ConnectionState
import com.mobilestore.scanner.ui.theme.AccentBg
import com.mobilestore.scanner.ui.theme.AccentOrange
import com.mobilestore.scanner.ui.theme.BorderColor
import com.mobilestore.scanner.ui.theme.GreenSuccess
import com.mobilestore.scanner.ui.theme.NavyDark
import com.mobilestore.scanner.ui.theme.RedDanger
import com.mobilestore.scanner.ui.theme.SurfaceWhite
import com.mobilestore.scanner.ui.theme.TextMuted
import com.mobilestore.scanner.ui.theme.TextPrimary
import com.mobilestore.scanner.viewmodel.ScannerViewModel

/**
 * Экран 5: Настройки, подключение к MobileStore на ПК и интервал паузы сканера.
 */
@Composable
fun SettingsScreen(vm: ScannerViewModel) {
    val config by vm.serverConfig.collectAsState()
    val connState by vm.connectionState.collectAsState()

    var host by remember(config.host) { mutableStateOf(config.host) }
    var portText by remember(config.port) { mutableStateOf(config.port.toString()) }
    var pinToken by remember(config.pinToken) { mutableStateOf(config.pinToken) }
    var deviceName by remember(config.deviceName) { mutableStateOf(config.deviceName) }

    val chipColors = FilterChipDefaults.filterChipColors(
        selectedContainerColor = AccentBg,
        selectedLabelColor = AccentOrange,
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            Text("Kompýutere baglanmak", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = NavyDark)
            ConnectionGlowDot(state = connState, size = 24.dp)
        }

        if (connState is ConnectionState.Error) {
            Text(
                text = (connState as ConnectionState.Error).message,
                fontSize = 12.sp,
                color = RedDanger,
                fontWeight = FontWeight.SemiBold,
            )
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
            border = BorderStroke(1.dp, BorderColor),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("Kompýuteriň IP ýa-da ws://IP:port (mysal: 192.168.1.15)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = portText,
                    onValueChange = { portText = it },
                    label = { Text("WebSocket port (adaty 8765)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = pinToken,
                    onValueChange = { pinToken = it },
                    label = { Text("Kompýuterdäki 6 sanly PIN-kod") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = deviceName,
                    onValueChange = { deviceName = it },
                    label = { Text("Telefonyň ady (kompýuterde görünýär)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    text = "Enjam ID: ${config.deviceId}",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    color = TextMuted,
                )

                Spacer(Modifier.height(4.dp))

                Button(
                    onClick = {
                        val port = portText.toIntOrNull()?.coerceIn(1024, 65535) ?: 8765
                        vm.saveAndConnect(host, port, pinToken, deviceName)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                ) {
                    Text("Ýatda sakla we baglan")
                }

                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(
                        onClick = { vm.reconnect() },
                        border = BorderStroke(1.dp, BorderColor),
                        modifier = Modifier.weight(1f),
                    ) { Text("Täzeden baglan", color = NavyDark) }

                    OutlinedButton(
                        onClick = { vm.disconnect() },
                        border = BorderStroke(1.dp, BorderColor),
                        modifier = Modifier.weight(1f),
                    ) { Text("Baglanyşygy kes", color = RedDanger) }
                }
            }
        }

        // Настройка паузы между сканированиями
        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
            border = BorderStroke(1.dp, BorderColor),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "Skan arasyndaky arakesme",
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                    color = NavyDark,
                )
                Text(
                    "Her okalan koddan soň kamera goňşy ştrihkodlary gaýtadan okamazlygy üçin gysga arakesme. Maslahat: 2.5 s.",
                    fontSize = 12.sp,
                    color = TextMuted,
                )
                val presets = listOf(
                    1_500L to "1.5 s",
                    2_500L to "2.5 s (masl.)",
                    3_000L to "3.0 s",
                    4_000L to "4.0 s",
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    presets.forEach { (ms, label) ->
                        FilterChip(
                            selected = config.scanCooldownMs == ms,
                            onClick = { vm.updateScanCooldown(ms) },
                            label = { Text(label, fontSize = 12.sp) },
                            colors = chipColors,
                        )
                    }
                }
            }
        }

        Text(
            text = "Ulgam internetsiz, diňe ýerli Wi-Fi arkaly işleýär. " +
                "Ähli maglumatlar we hasaplar MobileStore kompýuterinde saklanýar.",
            fontSize = 12.sp,
            color = TextMuted,
        )
    }
}
