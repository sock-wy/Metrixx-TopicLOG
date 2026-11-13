"""Generating MP4: MYCAST script + MP3 -> scene images (DXcharts / ApexCharts) -> Shotstack -> MP4.

Steps (each writes into the job folder, so a step can be re-run on its own):
  1 align     ElevenLabs forced alignment: when every word of the script is spoken  -> words.json
  2 plan      Claude reads the script (and the Topic Log digest): scenes, numbers, anchors -> plan.json
  3 data      prices for the tickers in the plan (Yahoo for now), facts, number checks   -> data.json, checks.json
  4 charts    scene.html per scene -> PNG, plus a contact sheet                           -> charts/*.png, contact.png
  -- review: the person looks at the contact sheet and the checks, then continues --
  5 timeline  scenes timed to their anchor phrases, captions, footer, voice               -> edit.json, captions.srt
  6 render    upload to Shotstack, render, download                                       -> <slug>.mp4

Run from the app (Apps > Generating MP4) or the command line:  python3 -m mp4gen <script.md> <audio.mp3> [--out DIR]
"""
