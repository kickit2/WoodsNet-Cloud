with open('web_portal/app.js', 'r') as f:
    text = f.read()

text = text.replace("data.mule_mappings", "data.camera_mappings")
text = text.replace("'data-mule'", "'data-camera'")
text = text.replace("muleId", "cameraId")
text = text.replace("mules from mappings", "cameras from mappings")

with open('web_portal/app.js', 'w') as f:
    f.write(text)

