import os
import cv2
import uuid
import easyocr
import numpy as np
import zipfile
import io
import time
import pythoncom
import shutil
import tkinter as tk
from tkinter import filedialog
from flask import Flask, render_template, request, jsonify
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from deep_translator import GoogleTranslator

# Próba importu Photoshop COM
try:
    import win32com.client
    HAS_PS_COM = True
except ImportError:
    HAS_PS_COM = False

app = Flask(__name__)

# Konfiguracja folderów
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(BASE_DIR, 'static', 'input')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'static', 'output')

for p in [INPUT_FOLDER, OUTPUT_FOLDER]:
    Path(p).mkdir(parents=True, exist_ok=True)

reader_cache = {}

def get_reader(lang_code):
    if lang_code not in reader_cache:
        print(f"[DEBUG] Ładowanie EasyOCR: {lang_code}")
        reader_cache[lang_code] = easyocr.Reader([lang_code], gpu=False)
    return reader_cache[lang_code]

LANGUAGE_CONFIG = {
    "English": {"ocr": "en", "trans": "en"},
    "Korean": {"ocr": "ko", "trans": "ko"},
    "Japanese": {"ocr": "ja", "trans": "ja"},
    "Russian": {"ocr": "ru", "trans": "ru"},
    "Simplified Chinese": {"ocr": "ch_sim", "trans": "zh-CN"},
    "Traditional Chinese": {"ocr": "ch_tra", "trans": "zh-TW"}
}

def hex_to_bgr(hex_str):
    hex_str = hex_str.lstrip('#')
    rgb = tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
    return (rgb[2], rgb[1], rgb[0]) 

def add_invisible_anchors(pil_img):
    w, h = pil_img.size
    pil_img.putpixel((0, 0), (0, 0, 0, 1))
    pil_img.putpixel((w - 1, h - 1), (0, 0, 0, 1))
    return pil_img

def create_text_layer_image(img_w, img_h, bubbles):
    text_layer = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    font_path = "arial.ttf" 
    has_any = False
    for b in bubbles:
        if not b['selected'] or not b.get('translated'): continue
        has_any = True
        txt = str(b['translated'])
        ix, iy, iw, ih = int(b['x']), int(b['y']), int(b['w']), int(b['h'])
        l, t = (ix, iy) if iw > 0 else (ix + iw, iy + ih)
        abs_w, abs_h = abs(iw), abs(ih)
        fs = int(max(14, min(abs_h * 0.75, (abs_w * 1.5) / (len(txt) or 1))))
        try: font = ImageFont.truetype(font_path, fs)
        except: font = ImageFont.load_default()
        for off in [(-1,-1), (1,-1), (-1,1), (1,1)]:
            draw.text((l+off[0], t+off[1]), txt, font=font, fill=(0, 0, 0, 255))
        draw.text((l, t), txt, font=font, fill=(255, 255, 255, 255))
    return add_invisible_anchors(text_layer) if has_any else None

def extract_raw_ink(original_cv2_img, bubbles):
    h, w = original_cv2_img.shape[:2]
    ink_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    orig_pil = Image.fromarray(cv2.cvtColor(original_cv2_img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    has_any = False
    for b in bubbles:
        if not b['selected']: continue
        has_any = True
        ix, iy, iw, ih = int(b['x']), int(b['y']), int(b['w']), int(b['h'])
        l, r = (ix, ix+iw) if iw > 0 else (ix+iw, ix)
        t, bot = (iy, iy+ih) if ih > 0 else (iy+ih, iy)
        crop_box = (max(0, l), max(0, t), min(w, r), min(h, bot))
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]: continue
        
        crop = orig_pil.crop(crop_box)
        if b.get('shape') == 'circle':
            mask = Image.new('L', crop.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, crop.size[0], crop.size[1]), fill=255)
            ink_layer.paste(crop, (l, t), mask)
        else:
            ink_layer.paste(crop, (l, t))
    return add_invisible_anchors(ink_layer) if has_any else None

def save_ora(cleaned_cv2_img, ink_pil_img, text_pil_img, output_path):
    h_bg, w_bg = cleaned_cv2_img.shape[:2]
    bg_img = Image.fromarray(cv2.cvtColor(cleaned_cv2_img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    temp_dir = os.path.join(OUTPUT_FOLDER, "tmp_" + str(uuid.uuid4())[:5])
    data_dir = os.path.join(temp_dir, "data"); os.makedirs(data_dir, exist_ok=True)
    bg_img.save(os.path.join(data_dir, "bg.png"))
    
    layers_xml = []
    if text_pil_img:
        text_pil_img.save(os.path.join(data_dir, "ocr.png"))
        layers_xml.append('<layer name="Tlumaczenie" src="data/ocr.png" opacity="1.0" visible="true"/>')
    if ink_pil_img:
        ink_pil_img.save(os.path.join(data_dir, "ink.png"))
        layers_xml.append('<layer name="Oryginalne Wycinki" src="data/ink.png" opacity="1.0" visible="true"/>')
    layers_xml.append('<layer name="Tlo" src="data/bg.png" opacity="1.0" visible="true"/>')

    xml = f'<?xml version="1.0" encoding="UTF-8"?><image w="{w_bg}" h="{h_bg}"><stack>{" ".join(layers_xml)}</stack></image>'
    with open(os.path.join(temp_dir, "stack.xml"), "w", encoding="utf-8") as f: f.write(xml)
    with open(os.path.join(temp_dir, "mimetype"), "w") as f: f.write("image/openraster")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(temp_dir):
            for file in files:
                full = os.path.join(root, file); rel = os.path.relpath(full, temp_dir); z.write(full, rel)
    shutil.rmtree(temp_dir)

def detect_shape(img, x, y, w, h):
    try:
        roi = img[max(0, y):min(img.shape[0], y+h), max(0, x):min(img.shape[1], x+w)]
        if roi.size == 0: return "rect"
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (11, 11), 0)
        _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours: return "rect"
        cnt = max(contours, key=cv2.contourArea)
        if len(cnt) >= 5:
            ellipse = cv2.fitEllipse(cnt)
            (ex, ey), (emajor, eminor), eangle = ellipse
            ellipse_area = (np.pi * emajor * eminor) / 4
            cnt_area = cv2.contourArea(cnt)
            match_ratio = cnt_area / ellipse_area if ellipse_area > 0 else 0
            extent = cnt_area / (w * h) if (w * h) > 0 else 0
            if match_ratio > 0.80 and extent < 0.88:
                return "circle"
        return "rect"
    except:
        return "rect"

def merge_nearby_boxes(ocr_results, dist_threshold=25):
    if not ocr_results: return []
    boxes = []
    for (bbox, text, prob) in ocr_results:
        p1, p2, p3, p4 = bbox
        boxes.append({'x1': int(p1[0]), 'y1': int(p1[1]), 'x2': int(p3[0]), 'y2': int(p3[1]), 'text': text})
    
    merged = True
    while merged:
        merged = False
        new_boxes = []
        while boxes:
            curr = boxes.pop(0)
            combined = False
            for other in new_boxes:
                if not (curr['x1'] - dist_threshold > other['x2'] or curr['x2'] + dist_threshold < other['x1'] or 
                        curr['y1'] - dist_threshold > other['y2'] or curr['y2'] + dist_threshold < other['y1']):
                    other['x1'], other['y1'] = min(curr['x1'], other['x1']), min(curr['y1'], other['y1'])
                    other['x2'], other['y2'] = max(curr['x2'], other['x2']), max(curr['y2'], other['y2'])
                    other['text'] = other['text'] + " " + curr['text']
                    merged = True; combined = True; break
            if not combined: new_boxes.append(curr)
        boxes = new_boxes
    return boxes

def grow_to_bubble_edge(img, x1, y1, x2, y2):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h_img, w_img = gray.shape
    _, mask = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
    max_grow = 100
    for _ in range(max_grow):
        if y1 <= 0 or np.any(mask[y1, x1:x2]): break
        y1 -= 1
    for _ in range(max_grow):
        if y2 >= h_img-1 or np.any(mask[y2, x1:x2]): break
        y2 += 1
    for _ in range(max_grow):
        if x1 <= 0 or np.any(mask[y1:y2, x1]): break
        x1 -= 1
    for _ in range(max_grow):
        if x2 >= w_img-1 or np.any(mask[y1:y2, x2]): break
        x2 += 1
    padding = 8
    return x1 + padding, y1 + padding, (x2 - x1) - (padding * 2), (y2 - y1) - (padding * 2)

# --- MATEMATYKA GRADIENTU (Numpy) ---
def generate_gradient_patch(w, h, color1, color2, angle_css, stop1, stop2):
    # Tłumaczenie kąta CSS na wektor w przestrzeni obrazu
    theta = np.radians(angle_css)
    vx, vy = np.sin(theta), -np.cos(theta)
    
    x = np.linspace(-w/2, w/2, w)
    y = np.linspace(-h/2, h/2, h)
    xx, yy = np.meshgrid(x, y)
    
    # Rzutowanie punktów na wektor kierunkowy gradientu
    proj = xx * vx + yy * vy
    
    # Znajdowanie wartości min/max dla rogów, by wyskalować gradient 0-1
    corners = np.array([[-w/2, -h/2], [w/2, -h/2], [-w/2, h/2], [w/2, h/2]])
    projs = corners[:, 0] * vx + corners[:, 1] * vy
    p_min, p_max = projs.min(), projs.max()
    
    if p_max - p_min < 1e-5:
        t = np.zeros_like(proj)
    else:
        t = (proj - p_min) / (p_max - p_min)
    
    # Aplikacja poziomów (stops)
    if stop2 <= stop1: stop2 = stop1 + 0.001
    t = (t - stop1) / (stop2 - stop1)
    t = np.clip(t, 0, 1)
    
    # Interpolacja kolorów
    c1 = np.array(color1, dtype=float)
    c2 = np.array(color2, dtype=float)
    
    t_expanded = t[:, :, np.newaxis]
    patch = c1 + t_expanded * (c2 - c1)
    return patch.astype(np.uint8)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/select_dir')
def select_dir():
    root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
    path = filedialog.askdirectory(); root.destroy()
    return jsonify({"path": path})

@app.route('/upload', methods=['POST'])
def upload():
    for f in os.listdir(INPUT_FOLDER):
        try: os.remove(os.path.join(INPUT_FOLDER, f))
        except: pass
    files = request.files.getlist('images')
    ui_lang = request.form.get('language', 'English')
    conf = float(request.form.get('confidence', 0.4))
    lang_info = LANGUAGE_CONFIG.get(ui_lang, LANGUAGE_CONFIG["English"])
    reader = get_reader(lang_info["ocr"])
    results = []
    
    for file in files:
        if not file: continue
        fname = str(uuid.uuid4())[:8] + "_" + file.filename
        path = os.path.join(INPUT_FOLDER, fname); file.save(path)
        img = cv2.imread(path)
        if img is None: continue
        h_img, w_img = img.shape[:2]
        
        raw_ocr = reader.readtext(path)
        valid_ocr = [r for r in raw_ocr if r[2] >= conf]
        merged_blocks = merge_nearby_boxes(valid_ocr)
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bubbles = []
        for block in merged_blocks:
            roi = gray[max(0, block['y1']):min(h_img, block['y2']), max(0, block['x1']):min(w_img, block['x2'])]
            if roi.size > 0 and np.mean(roi) > 180: 
                nx, ny, nw, nh = grow_to_bubble_edge(img, block['x1'], block['y1'], block['x2'], block['y2'])
                detected_shape = detect_shape(img, nx, ny, nw, nh)
                bubbles.append({
                    "id": str(uuid.uuid4())[:6], "text": block['text'],
                    "x": nx, "y": ny, "w": nw, "h": nh,
                    "selected": True, "shape": detected_shape, 
                    "fillType": "solid", "color": "#ffffff", "color2": "#000000",
                    "gradAngle": 180, "gradStop1": 0, "gradStop2": 100
                })
        results.append({"filename": fname, "original_name": file.filename, "bubbles": bubbles, "width": w_img, "height": h_img})
    return jsonify(results)

@app.route('/re_ocr', methods=['POST'])
def re_ocr():
    data = request.json
    lang_info = LANGUAGE_CONFIG.get(data.get('language'), LANGUAGE_CONFIG["English"])
    img = cv2.imread(os.path.join(INPUT_FOLDER, data['filename']))
    if img is None: return jsonify({"text": ""})
    x, y, w, h = int(data['x']), int(data['y']), int(data['w']), int(data['h'])
    x1, x2 = (x, x+w) if w > 0 else (x+w, x)
    y1, y2 = (y, y+h) if h > 0 else (y+h, y)
    crop = img[max(0,y1):min(img.shape[0], y2), max(0,x1):min(img.shape[1], x2)]
    if crop.size == 0: return jsonify({"text": ""})
    result = get_reader(lang_info["ocr"]).readtext(crop)
    return jsonify({"text": " ".join([res[1] for res in result])})

@app.route('/process', methods=['POST'])
def process():
    data = request.json
    save_path = data.get('save_path') or OUTPUT_FOLDER
    export_type = data.get('export_type', 'none')
    do_translate = data.get('do_translate', False)
    target_lang = data.get('target_lang', 'pl')
    ui_lang = data.get('ui_lang', 'English')
    src_lang = LANGUAGE_CONFIG.get(ui_lang, {"trans": "auto"})["trans"]

    if export_type == 'psd': pythoncom.CoInitialize()

    for item in data['image_data']:
        path = os.path.join(INPUT_FOLDER, item['filename'])
        original_img = cv2.imread(path)
        if original_img is None: continue
        
        if do_translate:
            translator = GoogleTranslator(source=src_lang, target=target_lang)
            for b in item['bubbles']:
                if b['selected'] and b['text'].strip():
                    try: b['translated'] = translator.translate(b['text'])
                    except: b['translated'] = b['text']

        img_cleaned = original_img.copy()
        
        # --- WYPEŁNIANIE W PROGRAMIE ---
        for b in item['bubbles']:
            if b.get('selected'):
                fill_type = b.get('fillType', 'solid')
                shape = b.get('shape', 'rect')
                c1 = hex_to_bgr(b.get('color', '#ffffff'))
                ix, iy, iw, ih = int(b['x']), int(b['y']), int(b['w']), int(b['h'])
                angle = float(b.get('angle', 0))
                
                if iw <= 0 or ih <= 0: continue
                
                img_h, img_w = img_cleaned.shape[:2]
                
                # 1. Tworzenie pełnowymiarowej maski obrazka
                full_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                
                # Rysowanie bazowego kształtu na masce na oryginalnej pozycji (bez obrotu)
                if shape == 'circle':
                    cv2.ellipse(full_mask, (ix + iw//2, iy + ih//2), (abs(iw//2), abs(ih//2)), 0, 0, 360, 255, -1)
                elif shape == 'triangle':
                    pts = np.array([[ix + iw//2, iy], [ix, iy + ih], [ix + iw, iy + ih]], np.int32)
                    cv2.fillPoly(full_mask, [pts], 255)
                elif shape == 'polygon' and 'points' in b:
                    pts = []
                    for p in b['points']:
                        px = ix + int((p['x'] / 100) * iw)
                        py = iy + int((p['y'] / 100) * ih)
                        pts.append([px, py])
                    pts = np.array(pts, np.int32)
                    cv2.fillPoly(full_mask, [pts], 255)
                else: # domyślnie rect
                    cv2.rectangle(full_mask, (ix, iy), (ix + iw, iy + ih), 255, -1)
                
                cx, cy = ix + iw/2, iy + ih/2
                
                # OBRÓT MASKI (jeśli kąt > 0)
                if angle != 0:
                    M = cv2.getRotationMatrix2D((cx, cy), -angle, 1.0) # -angle bo CSS ma inny kierunek niż OpenCV
                    full_mask = cv2.warpAffine(full_mask, M, (img_w, img_h))
                
                # 2. Tworzenie pełnowymiarowej warstwy z kolorem/gradientem
                full_patch = np.zeros_like(img_cleaned)
                if fill_type == 'solid':
                    full_patch[:] = c1
                elif fill_type == 'gradient':
                    c2 = hex_to_bgr(b.get('color2', '#000000'))
                    grad_angle = float(b.get('gradAngle', 180))
                    stop1 = float(b.get('gradStop1', 0)) / 100.0
                    stop2 = float(b.get('gradStop2', 100)) / 100.0
                    
                    patch = generate_gradient_patch(max(1, iw), max(1, ih), c1, c2, grad_angle, stop1, stop2)
                    
                    # Wklejanie lokalnego gradientu na pełne tło
                    x1, y1 = max(0, ix), max(0, iy)
                    x2, y2 = min(img_w, ix+iw), min(img_h, iy+ih)
                    px1, py1 = x1 - ix, y1 - iy
                    px2, py2 = px1 + (x2 - x1), py1 + (y2 - y1)
                    if x2 > x1 and y2 > y1:
                        full_patch[y1:y2, x1:x2] = patch[py1:py2, px1:px2]
                        
                    # Jeżeli element jest obrócony, obracamy też warstwę gradientu, by kąty się zgadzały z podglądem na stronie
                    if angle != 0:
                        full_patch = cv2.warpAffine(full_patch, M, (img_w, img_h))
                
                # 3. Nakładanie warstwy na oryginalny obraz (Mieszanie z maską)
                mask_bool = full_mask == 255
                img_cleaned[mask_bool] = full_patch[mask_bool]
        
        orig_base = item['original_name'].rsplit('.', 1)[0]
        clean_png_path = os.path.join(save_path, f"clean_{orig_base}.png")
        cv2.imwrite(clean_png_path, img_cleaned)

        if export_type in ['ora', 'psd']:
            ink_layer = extract_raw_ink(original_img, item['bubbles'])
            text_layer = create_text_layer_image(item['width'], item['height'], item['bubbles'])
            if export_type == 'ora':
                save_ora(img_cleaned, ink_layer, text_layer, os.path.join(save_path, f"{orig_base}.ora"))
            elif export_type == 'psd' and HAS_PS_COM:
                try:
                    ps = win32com.client.Dispatch("Photoshop.Application")
                    doc_ps = ps.Open(os.path.abspath(clean_png_path))
                    if ink_layer:
                        ti = os.path.join(save_path, f"tmp_i_{item['filename']}.png"); ink_layer.save(ti)
                        fi = ps.Open(os.path.abspath(ti)); fi.Selection.SelectAll(); fi.Selection.Copy(); fi.Close(2)
                        ps.ActiveDocument = doc_ps; li = doc_ps.Paste(); li.Name = "Oryginalne Wycinki"
                        if os.path.exists(ti): os.remove(ti)
                    if do_translate and text_layer:
                        to = os.path.join(save_path, f"tmp_o_{item['filename']}.png"); text_layer.save(to)
                        fo = ps.Open(os.path.abspath(to)); fo.Selection.SelectAll(); fo.Selection.Copy(); fo.Close(2)
                        ps.ActiveDocument = doc_ps; lo = doc_ps.Paste(); lo.Name = "Tlumaczenie"
                        if os.path.exists(to): os.remove(to)
                    doc_ps.ArtLayers[doc_ps.ArtLayers.Count-1].Name = "Tlo"
                    doc_ps.SaveAs(os.path.abspath(os.path.join(save_path, f"{orig_base}.psd")), win32com.client.Dispatch("Photoshop.PhotoshopSaveOptions"), True)
                    doc_ps.Close(2)
                except Exception as e: print(f"PS Error: {e}")

    return jsonify({"status": "ok"})

@app.route('/check_ps')
def check_ps():
    if not HAS_PS_COM: return jsonify({"installed": False})
    pythoncom.CoInitialize()
    try:
        win32com.client.Dispatch("Photoshop.Application")
        return jsonify({"installed": True})
    except: return jsonify({"installed": False})

if __name__ == '__main__':
    app.run(debug=True, port=5000)