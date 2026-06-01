[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType = WindowsRuntime] | Out-Null
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
foreach ($v in $synth.AllVoices) {
    Write-Output ("{0} | {1}" -f $v.DisplayName, $v.Language)
}
