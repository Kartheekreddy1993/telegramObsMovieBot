import obsws_python as obs
import schedule
import time
import os
from datetime import datetime
import sys
import re
import json

# === CONFIG ===
with open("config.json", "r") as f:
    config = json.load(f)


file_path = config["NOTEPAD_FILE"]
scene_path = config["SCENE_PATH"]
obs_port = config["OBS_PORT"]

# Connect to OBS
cl = obs.ReqClient(host='localhost', port=obs_port, password='secret', timeout=3)

while True:
    response = cl.get_current_program_scene()

    # Print scene name and UUID
    print("Scene Name:", response.scene_name)
    print("Scene UUID:", response.scene_uuid)
    with open(scene_path, 'w', encoding='utf-8') as file:
        file.write(response.scene_name)
    if response.scene_name == "filler" and os.path.isfile(file_path) and os.stat(file_path).st_size > 0:
        print("Scene is 'FillerScene' and file is NOT empty.")
        with open(file_path, 'r', encoding='utf-8') as file:
            play_list = [line.strip() for line in file]
            print("Lines in file:", play_list)
            inputname = "selectsource"
            # Format the playlist for OBS input settings
            cl.set_current_program_scene("select")
            inputsettings = {'playlist': [{'hidden': False, 'selected': False, 'value': path.strip()} for path in play_list]}
            # Set input settings for the VLC source
            cl.set_input_settings(inputname, inputsettings, overlay=True)
        # 🧹 Clear the file contents at the end
        with open(file_path, 'w', encoding='utf-8') as file:
            file.truncate(0)  # This clears the file 
    time.sleep(5)            