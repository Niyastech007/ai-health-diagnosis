from flask import Flask, render_template, request, redirect, session, send_file
import pandas as pd
import joblib
import sqlite3
import bcrypt
import edge_tts
import asyncio
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
import matplotlib
matplotlib.use('Agg')
from datetime import datetime

app = Flask(__name__)
app.secret_key = "health_ai_secret"

conn = sqlite3.connect("users.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users(
id INTEGER PRIMARY KEY AUTOINCREMENT,
username TEXT UNIQUE,
password TEXT
)
""")

conn.commit()
conn.close()

# =============== REGISTER ===============
@app.route("/register", methods=["GET","POST"])
def register():

    error = None
    success = None

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        # Check password match
        if password != confirm:
            return render_template(
                "register.html",
                error="Passwords do not match"
            )

        conn = sqlite3.connect("users.db", timeout=10)
        c = conn.cursor()

        # Check if username exists
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        existing_user = c.fetchone()

        if existing_user:
            conn.close()
            return render_template(
                "register.html",
                error="Username already exists"
            )

        # Hash password
        hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

        # Save to database
        c.execute(
            "INSERT INTO users(username,password) VALUES(?,?)",
            (username, hashed_password.decode())
        )

        conn.commit()
        conn.close()

        return render_template(
            "register.html",
            success="Account created successfully! Please login."
        )

    return render_template("register.html")

# ================ LOGIN ===============================
@app.route("/login", methods=["GET","POST"])
def login():

    error = None

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"].strip()

        # check empty fields
        if username == "" or password == "":
            error = "Please enter username and password."
            return render_template("login.html", error=error)

        conn = sqlite3.connect("users.db")
        c = conn.cursor()

        c.execute("SELECT password FROM users WHERE username=?", (username,))
        result = c.fetchone()

        conn.close()

        # user not found
        if result is None:
            error = "User does not exist."
            return render_template("login.html", error=error)

        # wrong password
        if not bcrypt.checkpw(password.encode(), result[0].encode()):
            error = "Incorrect password."
            return render_template("login.html", error=error)

        # login success
        session["user"] = username
        return redirect("/")

    return render_template("login.html")

# =============== LOGOUT =================
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")

# ================= LOAD MODEL & SCALER =================
model = joblib.load("model.pkl")
scaler = joblib.load("scaler.pkl")

feature_names = ["Age", "TopBP", "BottomBP", "Sugar", "BMI", "ChestPain"]

DISCLAIMER = (
    "DISCLAIMER: This system is for educational and decision-support "
    "purposes only. It does not replace professional medical diagnosis."
)

# =============== DATABASE ==================
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ================= SEVERITY =================
def severity(bp_t, bp_b, sugar, bmi):

    score = 0

    # Blood pressure
    if bp_t > 140 or bp_b > 90:
        score += 1

    # Sugar levels
    if sugar > 140 and sugar <= 200:
        score += 1
    elif sugar > 200:
        score += 2

    # BMI
    if bmi > 30:
        score += 1

    # Final severity
    if score >= 3:
        return "HIGH"
    elif score >= 1:
        return "MEDIUM"
    else:
        return "LOW"

# ================= HEALTH CONTENT =================
def health_content(disease):
    plans = {
        "diabetes": {
            "diet": ["Low sugar diet", "Whole grains", "Green vegetables"],
            "lifestyle": "Daily walking and sugar monitoring",
            "advice": "Avoid sweets and soft drinks"
        },
        "heart disease": {
            "diet": ["Low salt diet", "Fruits", "Vegetables"],
            "lifestyle": "Stress control and exercise",
            "advice": "Avoid smoking and oily food"
        },
        "asthma": {
            "diet": ["Warm food", "Fruits", "Light meals"],
            "lifestyle": "Avoid dust and allergens",
            "advice": "Regular breathing exercises"
        }
    }

    return plans.get(disease.lower(), {
        "diet": ["Balanced diet", "Fresh food", "Adequate water"],
        "lifestyle": "Maintain active lifestyle",
        "advice": "Regular health check-up"
    })

# ================= SAVE HISTORY =================
def save_history(data, username):

    file_name = "patient_history.csv"

    data["User"] = username

    df = pd.DataFrame([data])

    if not os.path.exists(file_name):
        df.to_csv(file_name, index=False)
    else:
        df.to_csv(file_name, mode="a", header=False, index=False)

# ================= HOME ROUTE =================

@app.route("/", methods=["GET", "POST"])
def index():

    if "user" not in session:
        return redirect("/login")

    report = None
    prediction = None
    confidence = None
    sev = None
    severity_color = None

    if request.method == "POST":

        # Check if model loaded
        if model is None:
            return render_template(
                "index.html",
                error="AI model not loaded.",
                username=session.get("user")
            )

        try:
            name = request.form["name"] or "User"
            age = int(request.form["age"])
            topbp = int(request.form["topbp"])
            botbp = int(request.form["botbp"])
            sugar = int(request.form["sugar"])
            bmi = float(request.form["bmi"])
            chest = int(request.form["chest"])

        except:
            return render_template(
                "index.html",
                error="Invalid numeric values entered.",
                username=session.get("user")
            )

        input_df = pd.DataFrame(
            [[age, topbp, botbp, sugar, bmi, chest]],
            columns=feature_names
        )

        scaled_input = scaler.transform(input_df)

        prediction = model.predict(scaled_input)[0]
        confidence = max(model.predict_proba(scaled_input)[0]) * 100

        sev = severity(topbp, botbp, sugar, bmi)

        if sev == "HIGH":
            severity_color = "danger"
        elif sev == "MEDIUM":
            severity_color = "warning"
        else:
            severity_color = "success"

        content = health_content(prediction)

        # SAVE HISTORY
        save_history({
            "DateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Name": name,
            "Age": age,
            "TopBP": topbp,
            "BottomBP": botbp,
            "Sugar": sugar,
            "BMI": bmi,
            "ChestPain": chest,
            "PredictedDisease": prediction,
            "Severity": sev,
            "Confidence": f"{confidence:.2f}%"
        }, session["user"])

        report = f"""
==============================
AI SMART HEALTH DIAGNOSIS REPORT
==============================

👤 PATIENT DETAILS
------------------------------
Name: {name}
Age: {age}
Date: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}

🧬 AI PREDICTION SUMMARY
------------------------------
Predicted Condition: {prediction.upper()}
Confidence Level: {confidence:.2f}%
Risk Severity: {sev}

📊 HEALTH PARAMETERS
------------------------------
Systolic BP: {topbp} mmHg
Diastolic BP: {botbp} mmHg
Blood Sugar: {sugar} mg/dL
BMI: {bmi}
Chest Pain: {"Yes" if chest == 1 else "No"}

🧠 AI ANALYSIS EXPLANATION
------------------------------
The AI model evaluated multiple physiological parameters
including blood pressure, sugar level, body mass index,
age and chest pain indicator.

The Random Forest algorithm uses ensemble learning
to improve predictive accuracy and decision reliability.

🥗 DIET RECOMMENDATIONS
------------------------------
1. {content['diet'][0]}
2. {content['diet'][1]}
3. {content['diet'][2]}

🏃 LIFESTYLE RECOMMENDATIONS
------------------------------
{content['lifestyle']}

💊 MEDICAL ADVISORY
------------------------------
{content['advice']}

----------------------------------------------------------
🧬 AI HEALTH INTERPRETATION
----------------------------------------------------------
Based on the entered medical parameters, the AI system
analyzes patterns from historical health datasets.

The prediction represents the most probable health
condition matching the provided physiological data.

The system evaluates:
• Blood pressure variations
• Blood sugar levels
• Body mass index
• Chest pain symptoms
• Patient age factor

This helps identify potential health risks early.

----------------------------------------------------------
📉 HEALTH RISK FACTOR ANALYSIS
----------------------------------------------------------
Risk factors considered during prediction include:

• Elevated blood pressure levels
• High blood sugar concentration
• Increased BMI indicating obesity
• Presence of chest pain symptoms

Multiple abnormal parameters increase the probability
of developing cardiovascular or metabolic disorders.

----------------------------------------------------------
🛡 PREVENTIVE HEALTH GUIDELINES
----------------------------------------------------------
To maintain better long-term health:

• Follow a balanced nutritional diet
• Engage in regular physical activity
• Maintain healthy body weight
• Reduce salt and sugar intake
• Drink adequate water daily
• Manage stress through relaxation techniques

----------------------------------------------------------
📊 HEALTH MONITORING RECOMMENDATIONS
----------------------------------------------------------
Patients are advised to monitor the following
health parameters regularly:

• Blood Pressure (BP)
• Blood Sugar Levels
• Body Mass Index (BMI)
• Physical activity levels

Regular monitoring helps detect health risks
before they become severe medical conditions.

----------------------------------------------------------
🚨 WARNING SIGNS TO CONSULT A DOCTOR
----------------------------------------------------------
Seek medical attention if you experience:

• Persistent chest pain
• Shortness of breath
• Severe fatigue
• Extremely high blood pressure
• Sudden dizziness or fainting

Early consultation helps prevent serious complications.

⚖ DISCLAIMER
------------------------------
{DISCLAIMER}
"""

    return render_template(
    "index.html",
    report=report,
    prediction=prediction,
    confidence=confidence,
    severity=sev,
    severity_color=severity_color,
    username=session.get("user")
)

# ================= VIEW HISTORY =================
@app.route("/history")
def history():

    file_name = "patient_history.csv"

    if not os.path.exists(file_name):
        return render_template("history.html", data=[])

    df = pd.read_csv(file_name)

    username = session["user"]

    if "User" not in df.columns:
        return render_template("history.html", data=[])

    user_data = df[df["User"] == username]

    data = user_data.values.tolist()

    return render_template("history.html", data=data)
# ================= FEATURE IMPORTANCE GRAPH =================
@app.route("/feature-graph")
def feature_graph():

    import matplotlib.pyplot as plt

    importances = model.feature_importances_
    features = feature_names

    plt.figure(figsize=(8,5))
    plt.barh(features, importances,color="purple")
    plt.xlabel("Feature Importance")
    plt.title("Explainable AI – Feature Importance")
    plt.tight_layout()

    path = "static/feature_graph.png"
    plt.savefig(path)
    plt.close()

    return send_file(path, mimetype="image/png")

# ================= PATIENT VS NORMAL GRAPH =================
@app.route("/comparison-graph", methods=["POST"])
def comparison_graph():

    import matplotlib.pyplot as plt
    import numpy as np

    topbp = int(request.form["topbp"])
    botbp = int(request.form["botbp"])
    sugar = int(request.form["sugar"])
    bmi = float(request.form["bmi"])

    parameters = ["Top BP", "Bottom BP", "Sugar", "BMI"]
    patient_values = [topbp, botbp, sugar, bmi]
    normal_values = [120, 80, 100, 22]

    x = np.arange(len(parameters))
    width = 0.35

    plt.figure(figsize=(9,5))

    patient_bars = plt.bar(x - width/2, patient_values, width, label="Patient", color="#ff0000")
    normal_bars = plt.bar(x + width/2, normal_values, width, label="Normal",color="#00C00A")

    for bar in patient_bars:
        height = bar.get_height()
        plt.text(bar.get_x()+bar.get_width()/2,
                 height+2,
                 f"{height}",
                 ha='center',
                 va='bottom',
                 fontweight='bold')

    for bar in normal_bars:
        height = bar.get_height()
        plt.text(bar.get_x()+bar.get_width()/2,
                 height+2,
                 f"{height}",
                 ha='center',
                 va='bottom',
                 fontweight='bold')

    plt.xticks(x, parameters)
    plt.ylabel("Values")
    plt.title("Patient vs Normal Health Comparison")
    plt.legend()
    plt.tight_layout()

    path = "static/comparison_graph.png"
    plt.savefig(path)
    plt.close()

    return send_file(path, mimetype="image/png")

# ================ CLEAN PDF ================
import re

def clean_pdf_text(text):
    # remove emojis and unsupported characters
    return re.sub(r'[^\x00-\x7F]+', '', text)

# ================= PDF GENERATION =================
pdfmetrics.registerFont(TTFont("DejaVu", "DejaVuSans.ttf"))
@app.route("/download-pdf", methods=["POST"])
def download_pdf():

    report_text = request.form["report_text"]
    report_text = clean_pdf_text(report_text)

    # remove box characters
    report_text = report_text.replace("□","")
    report_text = report_text.replace("■","")

    # extract patient details
    name = "Patient"
    age = "-"

    for line in report_text.split("\n"):
        if "Name:" in line:
            name = line.split("Name:")[1].strip()
        if "Age:" in line:
            age = line.split("Age:")[1].strip()

    file_path = "static/health_report.pdf"

    pdfmetrics.registerFont(TTFont("DejaVu", "DejaVuSans.ttf"))

    c = canvas.Canvas(file_path, pagesize=A4)

    width, height = A4
    margin = 50
    y = height - margin

    # ===== LOGO =====
    try:
        c.drawImage("static/logo.png", margin, height-90, width=60, height=60)
    except:
        pass

    # ===== HOSPITAL HEADER =====
    c.setFont("DejaVu", 18)
    c.drawCentredString(width/2, y, "AI SMART HEALTH DIAGNOSIS CENTER")

    y -= 25
    c.setFont("DejaVu", 12)
    c.drawCentredString(width/2, y, "AI Medical Analysis Report")

    y -= 30

    c.line(margin, y, width-margin, y)
    y -= 25

    # ===== PATIENT INFO TABLE =====
    data = [
        ["Patient Name", name],
        ["Age", age],
        ["Report Date", datetime.now().strftime('%d-%m-%Y %I:%M %p')]
    ]

    table = Table(data, colWidths=[150,300])

    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1),colors.lightgrey),
        ("TEXTCOLOR",(0,0),(0,-1),colors.black),
        ("GRID",(0,0),(-1,-1),1,colors.grey),
        ("FONTNAME",(0,0),(-1,-1),"DejaVu"),
        ("FONTSIZE",(0,0),(-1,-1),11),
    ]))

    table.wrapOn(c,width,height)
    table.drawOn(c,margin,y-70)

    y -= 100

    # ===== REPORT CONTENT =====
    lines = report_text.split("\n")

    for line in lines:

        if y < 80:
            c.showPage()
            c.setFont("DejaVu", 11)
            y = height - margin

        # colored section headers
        if (
            "PATIENT" in line
            or "PREDICTION" in line
            or "HEALTH PARAMETERS" in line
            or "ANALYSIS" in line
            or "DIET" in line
            or "LIFESTYLE" in line
            or "MEDICAL ADVISORY" in line
            or "PREVENTIVE" in line
            or "WARNING" in line
            or "DISCLAIMER" in line
        ):
            c.setFillColor(colors.darkblue)
            c.setFont("DejaVu",13)
        else:
            c.setFillColor(colors.black)
            c.setFont("DejaVu",11)

        c.drawString(margin,y,line)
        y -= 16

    # ===== SIGNATURE =====
    y -= 30
    c.line(width-200,y,width-50,y)

    c.setFont("DejaVu",11)
    c.drawString(width-180,y-15,"Authorized AI Medical System")

    # ===== FOOTER =====
    c.setFont("DejaVu",9)
    c.drawCentredString(
        width/2,
        30,
        "This AI-generated report is for educational and decision-support purposes only."
    )

    c.save()

    return send_file(file_path, as_attachment=True)
# ========== DELETE HISTORY =============

@app.route("/delete/<int:index>")
def delete_history(index):

    file_name = "patient_history.csv"

    df = pd.read_csv(file_name)

    username = session["user"]

    user_rows = df[df["User"] == username]

    if index < len(user_rows):

        drop_index = user_rows.index[index]

        df = df.drop(drop_index)

        df.to_csv(file_name, index=False)

    return redirect("/history")

# ============ VOICE ==============

@app.route("/doctor-voice", methods=["POST"])
def doctor_voice():

    name = request.form.get("name","User")
    disease = request.form.get("disease","Unknown").lower()
    severity = request.form.get("severity","Unknown")
    lang = request.form.get("lang","en")

    # ---------- ENGLISH CONTENT ----------
    english_tips = {
        "diabetes": """
        Maintain a low sugar diet.
        Eat whole grains, vegetables and fruits.
        Exercise regularly and monitor blood sugar levels.
        Avoid sweets and sugary drinks.
        """,

        "heart disease": """
        Follow a low fat and low salt diet.
        Avoid smoking and reduce stress.
        Perform regular physical activity such as walking.
        Monitor blood pressure regularly.
        """,

        "hypertension": """
        Reduce salt intake.
        Maintain a healthy body weight.
        Exercise daily and avoid stress.
        Monitor blood pressure regularly.
        """,

        "hypotension": """
        Drink enough water.
        Increase salt intake slightly if recommended by a doctor.
        Avoid sudden standing from sitting position.
        Eat small frequent meals.
        """,

        "obesity": """
        Reduce high calorie food.
        Increase fruits and vegetables in diet.
        Perform daily exercise.
        Maintain a balanced diet and healthy lifestyle.
        """,

        "healthy": """
        Maintain your current healthy lifestyle.
        Eat balanced diet and stay physically active.
        Continue regular health checkups.
        """
    }

    # ---------- TAMIL CONTENT ----------
    tamil_tips = {
        "diabetes": """
        சர்க்கரை குறைந்த உணவுகளை எடுத்துக்கொள்ளுங்கள்.
        காய்கறிகள் மற்றும் முழுதானிய உணவுகளை அதிகமாக உணுங்கள்.
        தினமும் உடற்பயிற்சி செய்யுங்கள்.
        சர்க்கரை அளவை அடிக்கடி பரிசோதிக்கவும்.
        """,

        "heart disease": """
        கொழுப்பு மற்றும் உப்பு குறைந்த உணவை எடுத்துக்கொள்ளுங்கள்.
        புகைபிடித்தலை தவிர்க்கவும்.
        தினமும் நடைபயிற்சி செய்யுங்கள்.
        இரத்த அழுத்தத்தை பரிசோதிக்கவும்.
        """,

        "hypertension": """
        உப்பு அளவை குறைக்கவும்.
        உடல் எடையை கட்டுப்படுத்தவும்.
        தினமும் உடற்பயிற்சி செய்யுங்கள்.
        மன அழுத்தத்தை குறைக்கவும்.
        """,

        "hypotension": """
        போதுமான அளவு தண்ணீர் குடிக்கவும்.
        மெதுவாக எழுந்து நிற்கவும்.
        சிறு அளவு உணவுகளை அடிக்கடி சாப்பிடவும்.
        மருத்துவரின் ஆலோசனையை பின்பற்றவும்.
        """,

        "obesity": """
        அதிக கலோரி உணவுகளை குறைக்கவும்.
        காய்கறி மற்றும் பழங்களை அதிகமாக உணுங்கள்.
        தினமும் உடற்பயிற்சி செய்யுங்கள்.
        ஆரோக்கியமான வாழ்க்கை முறையை பின்பற்றவும்.
        """,

        "healthy": """
        நீங்கள் ஆரோக்கியமாக இருக்கிறீர்கள்.
        சீரான உணவு முறையை தொடருங்கள்.
        உடற்பயிற்சியை தொடர்ந்து செய்யுங்கள்.
        """
    }

    # ---------- SELECT TEXT ----------
    if lang == "ta":

        tips = tamil_tips.get(disease,"ஆரோக்கியமான உணவு முறையை பின்பற்றவும்.")

        text = f"""
        வணக்கம் {name}.
        உங்கள் உடல்நல ஆய்வு முடிந்தது.

        கணிக்கப்பட்ட நோய் {disease}.
        அபாய நிலை {severity}.

        உடல்நல ஆலோசனைகள்:
        {tips}

        மேலும் ஆலோசனைக்காக மருத்துவரை அணுகவும்.
        """

        voice = "ta-IN-PallaviNeural"

    else:

        tips = english_tips.get(disease,"Please maintain a healthy lifestyle.")

        text = f"""
        Hello {name}.
        Your health analysis is complete.

        The predicted condition is {disease}.
        The severity level is {severity}.

        Health recommendations:
        {tips}

        Please consult a doctor for professional medical advice.
        """

        voice = "en-IN-PrabhatNeural"

    file_path = "static/doctor_voice.mp3"

    async def generate():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(file_path)

    asyncio.run(generate())

    return send_file(file_path)

# ============ ADMIN ==============
@app.route("/admin")
def admin():

    if "user" not in session or session["user"] != "admin":
        return redirect("/login")

    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    conn.close()

    if os.path.exists("patient_history.csv"):

        df = pd.read_csv("patient_history.csv")

        df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")

        df = df.dropna(subset=["DateTime"])

        total_predictions = len(df)

        today = datetime.now().date()

        today_predictions = len(df[df["DateTime"].dt.date == today])

        high_risk = len(df[df["Severity"] == "HIGH"])

        history = df.values.tolist()

    else:

        total_predictions = 0
        today_predictions = 0
        high_risk = 0
        history = []

    return render_template(
        "admin.html",
        total_users=total_users,
        total_predictions=total_predictions,
        high_risk=high_risk,
        today_predictions=today_predictions,
        history=history
    )
# ========== ADMIN USERS =============

@app.route("/admin/users")
def admin_users():

    if "user" not in session or session["user"] != "admin":
        return redirect("/login")

    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    c.execute("SELECT username FROM users")
    users = c.fetchall()

    conn.close()

    return render_template("admin_users.html", users=users)

# =========== ADMIN PREDICTIONS ============
@app.route("/admin/predictions")
def admin_predictions():

    if "user" not in session or session["user"] != "admin":
        return redirect("/login")

    if not os.path.exists("patient_history.csv"):
        return render_template("admin_predictions.html", data=[])

    df = pd.read_csv("patient_history.csv")
    data = df.values.tolist()

    return render_template("admin_predictions.html", data=data)

# =========== ADMIN RISK ================
@app.route("/admin/highrisk")
def admin_highrisk():

    if "user" not in session or session["user"] != "admin":
        return redirect("/login")

    if not os.path.exists("patient_history.csv"):
        return render_template("admin_highrisk.html", data=[])

    df = pd.read_csv("patient_history.csv")

    high = df[df["Severity"] == "HIGH"]

    data = high.values.tolist()

    return render_template("admin_highrisk.html", data=data)

if __name__ == "__main__":
    app.run(debug=False)
