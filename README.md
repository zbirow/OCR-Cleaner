# 🧹 Manga Cleaner

An intelligent, web-based tool for automating manga, comic, and webtoon cleaning and translation. 
Powered by **EasyOCR** and **OpenCV**, this tool automatically detects text bubbles, extracts the text, and allows you to seamlessly erase and redraw bubbles using solid colors, gradients, and custom vector shapes. It can also auto-translate text and export layered files for professional editing.

![Manga Cleaner Screenshot](https://raw.githubusercontent.com/zbirow/OCR-Cleaner/refs/heads/main/content.png)

## ✨ Features

### 🔍 Automated OCR & Detection
*   **Multi-language Support:** Detects English, Japanese, Korean, Russian, and Chinese (Simplified/Traditional).
*   **Smart Bubble Detection:** Automatically calculates bubble bounding boxes and estimates if a bubble is a rectangle or a circle.
*   **Adjustable Confidence:** Filter out false OCR readings with a simple slider.

### 🎨 Advanced Editing & Redrawing
Right-click on any detected bubble to access the powerful **Context Menu**:
*   **Versatile Shapes:** Draw Rectangles, Circles, Triangles, or **Custom Vector Polygons** (click around the bubble to create a perfect custom mask).
*   **Live Gradient Fills:** Apply Linear Gradients with adjustable angles (0-360°) and stops. The preview updates live on the image!
*   **Free Rotation:** Rotate any shape from 0° to 360° to perfectly match tilted comic panels.
*   **Eyedropper Tool:** Pick the exact background color directly from the manga page.
*   **Live Overlay Preview:** Toggle "Full Preview" to see exactly how the opaque mask will look before saving.

### 🌍 Auto-Translation
*   Uses `deep-translator` (Google Translate) to automatically translate detected text into English or Polish (easily expandable to other languages).

### 💾 Professional Export Options
Export your cleaned pages to a selected folder in three ways:
1.  **Only PNG:** Outputs the fully cleaned image (text removed and painted over).
2.  **Krita/GIMP (.ora):** Exports an OpenRaster file containing 3 layers: 
    *   Cleaned Background
    *   Original cut-out bubbles (Ink layer)
    *   Translated Text layer
3.  **Photoshop (.psd):** Automatically builds a fully layered `.psd` file. *(Note: Requires Windows and Adobe Photoshop to be installed on the machine).*

---

## 🛠️ Prerequisites

*   **Python 3.8+**
*   Windows OS (Highly recommended if you want to use the `.psd` Photoshop export feature via COM automation).

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/zbirow/OCR-Cleaner.git
   cd Manga-Cleaner
   ```

2. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. **Install the required dependencies:**
   Make sure you have a `requirements.txt` file, or install them manually:
   ```bash
   pip install flask opencv-python numpy easyocr Pillow deep-translator
   ```
   *If you want Photoshop PSD support on Windows, also install:*
   ```bash
   pip install pywin32
   ```

---

## 🚀 How to Use

1. **Start the server:**
   ```bash
   python app.py
   ```
2. **Open the web interface:**
   Go to `http://localhost:5000` in your web browser.
3. **Scan Images:**
   * Select your manga pages.
   * Choose the source language.
   * Click **SCAN OCR**. *(Note: The first time you use a specific language, EasyOCR will download the language model. This may take a minute).*
4. **Edit Bubbles:**
   * **Left-Click & Drag:** Move or resize the bounding boxes.
   * **Right-Click:** Open the Context Menu to change shape, color, rotation, gradient, or draw a Custom Vector Polygon.
5. **Save:**
   Select your desired export format (PNG, ORA, PSD), choose your target translation language, and click **SAVE ALL**. You will be prompted to select a folder on your computer where the files will be saved.

---

## 🖌️ Drawing Custom Polygons (Vectors)
To perfectly mask weirdly shaped text bubbles:
1. Right-click a bubble and select **🖊️ Draw Custom Polygon**.
2. Click around the text on the image to create anchor points (a red line will connect them).
3. Once the text is covered, click **✔ Finish Drawing** in the floating top menu.
4. You can now resize, rotate, and change the gradient of your custom shape just like any standard rectangle!

---

## ⚠️ Notes on Photoshop (.psd) Export
The `.psd` export option uses `win32com.client` to physically open Adobe Photoshop in the background, create the layers, paste the images, and save the `.psd` file. 
* Photoshop **must** be installed on the machine running the Python script.
* You might see Photoshop flash or open briefly while saving. This is normal behavior.

# Thanks to:
cicha szatynka  - ideas and tests
