# ChatbotFullstack

It takes in user message, instructions.txt and the database schema as input into openai LLM. It outputs a text and a list of actions. Each action can have a purpose, chart title, chart type and sql command itself. Each action is either data_for_charting or tabular_data and the layout will be different for each one. Each SQL command is executed using psycopg2 onto the postgres database. Then it's packaged ready to be received by the frontend which in this project my friend was using React
