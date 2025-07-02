import os
import json
import psycopg2
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
import psycopg2.extras 
from decimal import Decimal
import datetime

load_dotenv()
app = Flask(__name__)
client = OpenAI()

DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))

# unpacks incoming json, takes value from dict
def get_message(data):
    if not data:
        return jsonify({"error": "Invalid or missing JSON"}), 400
    
    value = data.get('question')

    if value is None:
        return jsonify({"error": "Missing 'question' field in JSON"}), 400

    return value, 200

# reads instructions txt file
def get_instructions():
    try:
        with open('instructions.txt', 'r') as file:
            return file.read()
    except FileNotFoundError:
        print("Error: instructions.txt not found. Please create it with LLM instructions.")
        return "No specific instructions provided."

# returns schema of all three db
def get_data():
    conn = None 
    cur = None  
    schema = [] 

    try:
        conn = psycopg2.connect(
            dbname =DB_NAME,
            user = DB_USER,
            password = DB_PASSWORD,
            host = DB_HOST,
            port = DB_PORT
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) 

        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE';
        """)

        tables = [row[0] for row in cur.fetchall()]

        for tbl in tables:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = %s
                ORDER BY ordinal_position;
            """, (tbl,))
            columns = cur.fetchall()
            column_description = ",".join(f" {name}:{dtype}" for name, dtype in columns)
            schema.append(f"Table '{tbl}', ({column_description})")

            cur.execute(f"SELECT * FROM {tbl} LIMIT 20;")
            sample_rows = [dict(row) for row in cur.fetchall()]

            for row_dict in sample_rows:
                for key, value in row_dict.items():
                    if isinstance(value, (datetime.date, datetime.datetime)):
                        row_dict[key] = value.strftime('%Y-%m-%d')
                    elif isinstance(value, Decimal): 
                        row_dict[key] = float(value) 

            if sample_rows:
                schema.append(f"Sample data for '{tbl}':")
                schema.append(json.dumps(sample_rows, indent=2)) 
            schema.append("\n") 

    except psycopg2.Error as e:
        print(f"Database schema retrieval error: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return schema

# combines msg, ins and data and sends to openai
def generate_dashboard_response(msg, ins, data):
    combined_prompt_content = (
        f"User Query: {msg}\n\n"
        f"Instructions for you (Cloud Cost Optimization Expert):\n{ins}\n\n"
        f"Relevant Data:\n"
        f"{data}\n\n"
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o", 
            messages=[
                {"role": "system", "content": "You are a helpful and concise cloud cost optimization assistant. Always respond with a JSON object as described in the user prompt."},
                {"role": "user", "content": combined_prompt_content}
            ]
        )
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            return response.choices[0].message.content
        else:
            print("Warning: LLM response content was None or empty.")
            return None 
    except OpenAIError as e:
        print(f"OpenAI API Error: {e}")
        return None 
    except Exception as e:
        print(f"An unexpected error occurred during LLM response generation: {e}")
        return None 

def execute_sql_query(sql_query, output_format='rows_and_columns'):
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(
            dbname = DB_NAME,
            user = DB_USER,
            password = DB_PASSWORD,
            host = DB_HOST,
            port = DB_PORT
        )

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(sql_query)

        if cur.description:
            results_dicts = [dict(row) for row in cur.fetchall()]
            for row_dict in results_dicts:
                for key, value in row_dict.items():
                    if isinstance(value, (datetime.date, datetime.datetime)):
                        row_dict[key] = value.strftime('%Y-%m-%d')
                    elif isinstance(value, Decimal):
                        row_dict[key] = float(value)

            if not results_dicts: 
                if output_format == 'raw_data_dicts':
                    return []
                else:
                    return {"labels": [], "values": []}

            if output_format == 'raw_data_dicts':
                return results_dicts
            else:
                structured_results = {
                    "labels": [], 
                    "values": []  
                }

                columns = list(results_dicts[0].keys())

                actual_label_col_name = columns[0] if columns else None
                actual_value_col_name = columns[1] if len(columns) > 1 else None

                if actual_label_col_name: 
                    for row_dict in results_dicts:
                        structured_results["labels"].append(row_dict[actual_label_col_name])
                        if actual_value_col_name: 
                            structured_results["values"].append(row_dict[actual_value_col_name])

                return structured_results
        else:
            conn.commit() 
            return {"message": "SQL command executed successfully, no data returned."}

    except psycopg2.Error as e:
        print(f"Database query failed for SQL: {sql_query}\nError: {e}")
        return {"error": f"Database query failed: {str(e)}"}
    except IndexError as e: 
        print(f"IndexError in execute_sql_query: Not enough columns for labels/values in query result for SQL: {sql_query}")
        return {"error": f"Data processing error: Not enough columns returned for charting. Query must return at least two columns for labels and values."}
    except Exception as e:
        print(f"An unexpected error occurred in execute_sql_query: {e}")
        return {"error": f"An unexpected error occurred during SQL execution: {str(e)}"}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# instructions_cache = get_instructions()
schema_cache = get_data()
line_by_line_schema = "\n".join(schema_cache)

@app.route('/ask', methods=['POST'])
def ask():
    request_data = request.get_json()

    msg, status_code = get_message(request_data)
    if status_code != 200:
        return msg, status_code

    # ins = instructions_cache
    ins = get_instructions()
    data = line_by_line_schema

    llm_response_content = generate_dashboard_response(msg, ins, data)
    llm_response_dict = json.loads(llm_response_content)

    overall_text_response = llm_response_dict.get('Text', "I've processed your request, but no specific text response was generated.")
    actions = llm_response_dict.get('Actions', [])
    final_frontend_payloads = []

    for action in actions:
        action_type = action.get("type")
        
        if action_type == "sql_query":
            sql_command = action.get("sql")
            purpose = action.get("purpose")
            chart_title = action.get("chart_title") 
            chart_type = action.get("chart_type") 
            series_columns = action.get("series_columns")
            
            print(sql_command)

            query_output_format = 'rows_and_columns' 
            if purpose == "tabular_data" or (series_columns and isinstance(series_columns, list)):
                query_output_format = 'raw_data_dicts' 
      
            db_query_result = execute_sql_query(sql_command, query_output_format)
            
            if isinstance(db_query_result, dict) and "error" in db_query_result:
                final_frontend_payloads.append({"type": "status", "message": db_query_result["error"]})
            elif isinstance(db_query_result, dict) and "message" in db_query_result:
                final_frontend_payloads.append({"type": "status", "message": db_query_result["message"]})
            else:
                payload = {
                    "type": "data_display",
                    "purpose": purpose,      
                    "data": db_query_result 
                }

                if purpose == "data_for_charting":
                    payload.update({
                        "chart_title": chart_title,   
                        "chart_type": chart_type,     
                        "series_columns": series_columns 
                    })
                final_frontend_payloads.append(payload) 

    return jsonify({
        "overall_response": overall_text_response, 
        "payloads": final_frontend_payloads        
    }), 200 

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)