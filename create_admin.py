import sqlite3
import bcrypt

username = "admin"
password = "admin123"

hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

conn = sqlite3.connect("users.db")
c = conn.cursor()

c.execute("INSERT INTO users(username,password) VALUES(?,?)",(username,hashed))

conn.commit()
conn.close()

print("Admin account created")