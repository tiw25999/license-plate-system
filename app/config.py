import os
import sys
from dotenv import load_dotenv
import httpx

# พิมพ์ข้อมูลเพื่อดีบัก
print("Starting config.py initialization")
print("Python version:", sys.version)
print("Current working directory:", os.getcwd())

# โหลดค่าตัวแปรแวดล้อมจากไฟล์ .env
load_dotenv()

# พิมพ์รายการตัวแปรทั้งหมดในสภาพแวดล้อม
print("All environment variables:", list(os.environ.keys()))
httpx._client.DEFAULT_TIMEOUT_CONFIG = httpx.Timeout(20.0, connect=10.0)

# ตรวจสอบว่าใช้การเชื่อมต่อแบบ Supabase หรือ PostgreSQL โดยตรง
DB_CONNECTION_TYPE = os.environ.get("DB_CONNECTION_TYPE", "supabase")

if DB_CONNECTION_TYPE.lower() == "supabase":
    # ใช้ Supabase
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

    print(f"SUPABASE_URL loaded: {'Yes' if SUPABASE_URL else 'No'}")
    print(f"SUPABASE_KEY loaded: {'Yes' if SUPABASE_KEY else 'No'}")

    try:
        # ตรวจสอบว่า SUPABASE_URL และ SUPABASE_KEY ถูกโหลดมาหรือไม่
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("ERROR: Missing Supabase credentials")
            raise ValueError("Missing Supabase URL or API Key in environment variables")

        # สร้าง Supabase client
        from supabase import create_client, Client
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase client created successfully")
        
        # สร้าง db_client เพื่อให้ใช้ interface เดียวกันกับ PostgreSQL
        db_client = supabase_client
        
    except Exception as e:
        print(f"Error creating Supabase client: {e}")
        raise
else:
    # ใช้ PostgreSQL โดยตรง
    DATABASE_URL = os.environ.get("DATABASE_URL")
    
    if not DATABASE_URL:
        print("ERROR: Missing DATABASE_URL")
        raise ValueError("Missing DATABASE_URL in environment variables")
    
    print(f"DATABASE_URL loaded: {'Yes' if DATABASE_URL else 'No'}")
    
    try:
        # ใช้ SQLAlchemy เพื่อเชื่อมต่อกับ PostgreSQL
        from sqlalchemy import create_engine
        from sqlalchemy.ext.declarative import declarative_base
        from sqlalchemy.orm import sessionmaker
        
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base = declarative_base()
        
        # สร้าง db_client เพื่อให้สามารถใช้ได้เหมือน supabase_client
        class PostgreSQLClient:
            def __init__(self, engine, SessionLocal):
                self.engine = engine
                self.SessionLocal = SessionLocal
                
            def get_session(self):
                return self.SessionLocal()
                
            # เพิ่มฟังก์ชันที่ใช้งานเหมือน supabase_client
            def table(self, table_name):
                return PostgreSQLTable(self, table_name)
                
            def rpc(self, function_name, params=None):
                return PostgreSQLRPC(self, function_name, params)
                
        class PostgreSQLTable:
            def __init__(self, client, table_name):
                self.client = client
                self.table_name = table_name
                self.conditions = []
                self.order_by_clause = None
                self.order_desc = False
                self.limit_val = None
                
            def select(self, columns="*"):
                self.select_columns = columns
                return self
                
            def insert(self, data):
                return PostgreSQLInsert(self.client, self.table_name, data)
                
            def update(self, data):
                return PostgreSQLUpdate(self.client, self.table_name, data, self.conditions)
                
            def delete(self):
                return PostgreSQLDelete(self.client, self.table_name, self.conditions)
                
            def eq(self, column, value):
                self.conditions.append((column, "=", value))
                return self
                
            def neq(self, column, value):
                self.conditions.append((column, "!=", value))
                return self
                
            def gt(self, column, value):
                self.conditions.append((column, ">", value))
                return self
                
            def lt(self, column, value):
                self.conditions.append((column, "<", value))
                return self
                
            def gte(self, column, value):
                self.conditions.append((column, ">=", value))
                return self
                
            def lte(self, column, value):
                self.conditions.append((column, "<=", value))
                return self
                
            def ilike(self, column, value):
                self.conditions.append((column, "ILIKE", value))
                return self
                
            def limit(self, limit_val):
                self.limit_val = limit_val
                return self
                
            def order(self, column, desc=False):
                self.order_by_clause = column
                self.order_desc = desc
                return self
                
            def single(self):
                self.limit_val = 1
                return self
                
            def execute(self):
                import sqlalchemy
                from sqlalchemy.sql import text
                
                session = self.client.get_session()
                try:
                    # สร้าง SQL query
                    query = f"SELECT {self.select_columns} FROM {self.table_name}"
                    
                    params = {}
                    if self.conditions:
                        query += " WHERE "
                        conditions = []
                        for i, (column, operator, value) in enumerate(self.conditions):
                            param_name = f"param_{i}"
                            if operator == "ILIKE":
                                conditions.append(f"{column} ILIKE :{param_name}")
                            else:
                                conditions.append(f"{column} {operator} :{param_name}")
                            params[param_name] = value
                        query += " AND ".join(conditions)
                    
                    if self.order_by_clause:
                        query += f" ORDER BY {self.order_by_clause}"
                        if self.order_desc:
                            query += " DESC"
                        else:
                            query += " ASC"
                    
                    if self.limit_val:
                        query += f" LIMIT {self.limit_val}"
                    
                    # Execute query
                    result = session.execute(text(query), params)
                    data = [dict(row) for row in result]
                    
                    # Return in format similar to Supabase
                    return type('obj', (object,), {
                        'data': data,
                        'error': None
                    })
                    
                except Exception as e:
                    return type('obj', (object,), {
                        'data': None,
                        'error': str(e)
                    })
                finally:
                    session.close()
                
        class PostgreSQLInsert:
            def __init__(self, client, table_name, data):
                self.client = client
                self.table_name = table_name
                self.data = data
                
            def execute(self):
                import sqlalchemy
                from sqlalchemy.sql import text
                
                session = self.client.get_session()
                try:
                    # Handle single dict or list of dicts
                    data_list = self.data if isinstance(self.data, list) else [self.data]
                    
                    results = []
                    for data_item in data_list:
                        columns = list(data_item.keys())
                        values = list(data_item.values())
                        
                        placeholders = [f":{col}" for col in columns]
                        query = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) RETURNING *"
                        
                        result = session.execute(text(query), data_item)
                        session.commit()
                        
                        # Ensure we get all returned columns
                        inserted_data = [dict(row) for row in result]
                        results.extend(inserted_data)
                    
                    return type('obj', (object,), {
                        'data': results,
                        'error': None
                    })
                    
                except Exception as e:
                    session.rollback()
                    return type('obj', (object,), {
                        'data': None,
                        'error': str(e)
                    })
                finally:
                    session.close()
                
        class PostgreSQLUpdate:
            def __init__(self, client, table_name, data, conditions):
                self.client = client
                self.table_name = table_name
                self.data = data
                self.conditions = conditions
                
            def eq(self, column, value):
                self.conditions.append((column, "=", value))
                return self
                
            def execute(self):
                import sqlalchemy
                from sqlalchemy.sql import text
                
                session = self.client.get_session()
                try:
                    # Build SET clause
                    set_clauses = []
                    params = {}
                    
                    for i, (column, value) in enumerate(self.data.items()):
                        set_param = f"set_param_{i}"
                        set_clauses.append(f"{column} = :{set_param}")
                        params[set_param] = value
                    
                    # Build WHERE clause
                    where_clauses = []
                    
                    for i, (column, operator, value) in enumerate(self.conditions):
                        where_param = f"where_param_{i}"
                        where_clauses.append(f"{column} {operator} :{where_param}")
                        params[where_param] = value
                    
                    # Build full query
                    query = f"UPDATE {self.table_name} SET {', '.join(set_clauses)}"
                    
                    if where_clauses:
                        query += f" WHERE {' AND '.join(where_clauses)}"
                    
                    query += " RETURNING *"
                    
                    # Execute query
                    result = session.execute(text(query), params)
                    session.commit()
                    
                    updated_data = [dict(row) for row in result]
                    
                    return type('obj', (object,), {
                        'data': updated_data,
                        'error': None
                    })
                    
                except Exception as e:
                    session.rollback()
                    return type('obj', (object,), {
                        'data': None,
                        'error': str(e)
                    })
                finally:
                    session.close()
                
        class PostgreSQLDelete:
            def __init__(self, client, table_name, conditions):
                self.client = client
                self.table_name = table_name
                self.conditions = conditions
                
            def eq(self, column, value):
                self.conditions.append((column, "=", value))
                return self
                
            def execute(self):
                import sqlalchemy
                from sqlalchemy.sql import text
                
                session = self.client.get_session()
                try:
                    # Build WHERE clause
                    where_clauses = []
                    params = {}
                    
                    for i, (column, operator, value) in enumerate(self.conditions):
                        param_name = f"param_{i}"
                        where_clauses.append(f"{column} {operator} :{param_name}")
                        params[param_name] = value
                    
                    # Build full query
                    query = f"DELETE FROM {self.table_name}"
                    
                    if where_clauses:
                        query += f" WHERE {' AND '.join(where_clauses)}"
                    
                    query += " RETURNING *"
                    
                    # Execute query
                    result = session.execute(text(query), params)
                    session.commit()
                    
                    deleted_data = [dict(row) for row in result]
                    
                    return type('obj', (object,), {
                        'data': deleted_data,
                        'error': None
                    })
                    
                except Exception as e:
                    session.rollback()
                    return type('obj', (object,), {
                        'data': None,
                        'error': str(e)
                    })
                finally:
                    session.close()
        
        class PostgreSQLRPC:
            def __init__(self, client, function_name, params=None):
                self.client = client
                self.function_name = function_name
                self.params = params or {}
                
            def execute(self):
                import sqlalchemy
                from sqlalchemy.sql import text
                
                session = self.client.get_session()
                try:
                    # สร้าง SQL query เรียก function
                    param_names = list(self.params.keys())
                    param_placeholders = [f":{name}" for name in param_names]
                    
                    query = f"SELECT * FROM {self.function_name}({', '.join(param_placeholders)})"
                    
                    # Execute query
                    result = session.execute(text(query), self.params)
                    session.commit()
                    
                    data = [dict(row) for row in result]
                    
                    return type('obj', (object,), {
                        'data': data,
                        'error': None
                    })
                    
                except Exception as e:
                    session.rollback()
                    return type('obj', (object,), {
                        'data': None,
                        'error': str(e)
                    })
                finally:
                    session.close()
        
        # สร้าง client
        db_client = PostgreSQLClient(engine, SessionLocal)
        supabase_client = db_client  # เพื่อความเข้ากันได้กับโค้ดเดิม
        
        print("PostgreSQL client created successfully")
        
    except Exception as e:
        print(f"Error creating PostgreSQL client: {e}")
        raise