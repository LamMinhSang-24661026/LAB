import gradio as gr
import pandas as pd
import pyodbc
from sklearn.ensemble import RandomForestClassifier

# Khai báo chuỗi cấu hình kết nối hệ thống chung
SERVER_INFO = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=127.0.0.1,1433;"
    "UID=sa;"
    "PWD=Vietnam@123;"
    "TrustServerCertificate=yes;"
)

# Hàm tự động kiểm tra và tạo sạch Database + Dữ liệu mẫu nếu hệ thống chưa có Northwind
def init_database_if_not_exists():
    conn = pyodbc.connect(SERVER_INFO + "DATABASE=master;", autocommit=True)
    cursor = conn.cursor()
    
    # Kiểm tra xem DB Northwind đã tồn tại chưa
    cursor.execute("SELECT name FROM sys.databases WHERE name = 'Northwind'")
    db_exists = cursor.fetchone()
    
    if not db_exists:
        print("⚠️ Không tìm thấy Database Northwind! Đang tự động khởi tạo lại...")
        cursor.execute("CREATE DATABASE Northwind")
        conn.close()
        
        # Kết nối trực tiếp vào DB Northwind để dựng bảng và nạp dữ liệu mẫu
        conn_db = pyodbc.connect(SERVER_INFO + "DATABASE=Northwind;", autocommit=True)
        cursor_db = conn_db.cursor()
        
        # Tạo bảng Products theo cấu trúc Northwind
        cursor_db.execute("""
        CREATE TABLE Products (
            ProductID INT PRIMARY KEY,
            ProductName NVARCHAR(50),
            CategoryID INT,
            UnitPrice DECIMAL(10,2)
        )
        """)
        
        # Tạo bảng Order Details
        cursor_db.execute("""
        CREATE TABLE [Order Details] (
            OrderID INT,
            ProductID INT,
            UnitPrice DECIMAL(10,2),
            Quantity INT
        )
        """)
        
        # Bơm 77 dòng dữ liệu mẫu (Sử dụng dấu ? để truyền tham số an toàn, tránh lỗi Invalid Column)
        for i in range(1, 78):
            cat_id = (i % 8) + 1  # Phân bổ đều CategoryID từ 1 đến 8 để mô hình học phân loại
            price = 10.0 + (i * 2.5)
            prod_name = f"Product {i}"
            
            # Sử dụng dấu ? để SQL Server nhận biết chính xác đây là giá trị truyền vào chứ không phải tên cột
            cursor_db.execute("INSERT INTO Products (ProductID, ProductName, CategoryID, UnitPrice) VALUES (?, ?, ?, ?)", 
                              (i, prod_name, cat_id, price))
            
            cursor_db.execute("INSERT INTO [Order Details] (OrderID, ProductID, UnitPrice, Quantity) VALUES (?, ?, ?, ?)", 
                              (1000 + i, i, price, 10 + (i % 5)))
            
        print("✅ Khởi tạo Database Northwind và nạp dữ liệu mẫu thành công!")
        conn_db.close()
    else:
        conn.close()

# Hàm kết nối lấy dữ liệu để huấn luyện mô hình Random Forest
def load_data_from_sql():
    # Chạy kiểm tra đảm bảo DB luôn sẵn sàng trước khi đọc dữ liệu
    init_database_if_not_exists()
    
    conn = pyodbc.connect(SERVER_INFO + "DATABASE=Northwind;")
    
    # Câu lệnh SQL JOIN chuẩn theo bài học số 6 trong tài liệu thực hành
    query = """
    SELECT 
        p.ProductID, 
        p.CategoryID, 
        SUM(od.Quantity * od.UnitPrice) AS TotalSales 
    FROM [Order Details] od 
    JOIN Products p ON od.ProductID = p.ProductID 
    GROUP BY p.ProductID, p.CategoryID;
    """
    
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Chuẩn hóa ép tên cột về chữ thường để tránh lỗi phân biệt chữ hoa/thường trên Linux Docker
    df.columns = [c.lower() for c in df.columns]
    df.rename(columns={
        "productid": "ProductID", 
        "categoryid": "CategoryID", 
        "totalsales": "TotalSales"
    }, inplace=True)
    
    return df

# Tiến hành khởi chạy đồng bộ hóa dữ liệu và huấn luyện thuật toán Random Forest
try:
    df_data = load_data_from_sql()
    df_data.dropna(subset=['ProductID', 'CategoryID', 'TotalSales'], inplace=True)
    
    if df_data.empty:
        raise ValueError("Dữ liệu trống!")

    # Thiết lập biến đầu vào X và nhãn đầu ra y
    X = df_data[['TotalSales', 'ProductID']]
    y = df_data['CategoryID']
    
    # Khởi tạo thuật toán phân loại Random Forest
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    status_msg = f"✅ Kết nối thành công! Đã nạp thành công {len(df_data)} dòng dữ liệu từ SQL Server và huấn luyện mô hình!"
except Exception as e:
    df_data = pd.DataFrame(columns=['ProductID', 'CategoryID', 'TotalSales'])
    model = None
    status_msg = f"❌ Lỗi hệ thống: {str(e)}"

# Logic xử lý nút bấm trên web Gradio
def refresh_table():
    try:
        df_new = load_data_from_sql()
        return df_new[['ProductID', 'CategoryID', 'TotalSales']]
    except:
        return df_data[['ProductID', 'CategoryID', 'TotalSales']] if not df_data.empty else df_data

def predict_category(product_id, total_sales):
    if model is None:
        return "Hệ thống đang lỗi dữ liệu, không thể chạy dự đoán."
    try:
        input_features = pd.DataFrame([[total_sales, product_id]], columns=['TotalSales', 'ProductID'])
        prediction = model.predict(input_features)[0]
        return f"Mã loại sản phẩm (CategoryID) được mô hình Random Forest dự đoán là: {int(prediction)}"
    except Exception as err:
        return f"Lỗi nhập liệu: {str(err)}"

# Thiết kế giao diện Dashboard Web trực quan bằng Gradio Blocks
with gr.Blocks(title="Northwind Data Explorer & Classifier") as demo:
    gr.Markdown("# 🏪 ỨNG DỤNG TRỰC QUAN HÓA CSDL NORTHWIND & MÔ HÌNH PHÂN LOẠI (LAB_G)")
    gr.Markdown(f"**Trạng thái kết nối hệ thống:** {status_msg}")
    
    with gr.Tab("📊 Xem Dữ Liệu Northwind"):
        gr.Markdown("### Bảng tổng hợp dữ liệu sản phẩm (Products JOIN Order Details)")
        btn_refresh = gr.Button("Tải / Làm mới dữ liệu từ CSDL")
        
        display_df = df_data[['ProductID', 'CategoryID', 'TotalSales']] if not df_data.empty else df_data
        table_display = gr.Dataframe(value=display_df, interactive=False)
        btn_refresh.click(fn=refresh_table, outputs=table_display)
        
    with gr.Tab("🤖 Dự Đoán Phân Loại Sản Phẩm"):
        gr.Markdown("### Dự đoán CategoryID bằng Thuật toán Random Forest")
        
        with gr.Row():
            input_id = gr.Number(label="Nhập Mã sản phẩm (ProductID)", value=1)
            input_sales = gr.Number(label="Nhập Doanh số sản phẩm (TotalSales)", value=500)
            
        btn_predict = gr.Button("Chạy mô hình dự đoán")
        output_text = gr.Textbox(label="Kết quả phân loại từ mô hình")
        btn_predict.click(fn=predict_category, inputs=[input_id, input_sales], outputs=output_text)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)