package com.mobilestore.scanner.scanner

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

class FeedbackManager(context: Context) {
    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        val vm = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
        vm?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    private val toneGenerator: ToneGenerator? = runCatching {
        ToneGenerator(AudioManager.STREAM_NOTIFICATION, 85)
    }.getOrNull()

    fun onScanSuccess() {
        vibrate(55L)
        runCatching { toneGenerator?.startTone(ToneGenerator.TONE_PROP_BEEP, 100) }
    }

    fun onConfirmSuccess() {
        vibrate(90L)
        runCatching { toneGenerator?.startTone(ToneGenerator.TONE_PROP_ACK, 140) }
    }

    fun onError() {
        vibratePattern(longArrayOf(0, 70, 60, 120))
        runCatching { toneGenerator?.startTone(ToneGenerator.TONE_PROP_NACK, 200) }
    }

    private fun vibrate(ms: Long) {
        runCatching {
            vibrator?.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    private fun vibratePattern(timings: LongArray) {
        runCatching {
            vibrator?.vibrate(VibrationEffect.createWaveform(timings, -1))
        }
    }
}
