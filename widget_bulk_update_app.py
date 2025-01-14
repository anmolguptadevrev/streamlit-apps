#for in app experience
import streamlit as st
import requests
import json

def remove_dashboard_v1(obj):
    if isinstance(obj, dict):
        obj.pop("dashboard_v1", None)
        for value in obj.values():
            remove_dashboard_v1(value)
    elif isinstance(obj, list):
        for item in obj:
            remove_dashboard_v1(item)

def get_widget_data(base_url, token, widget_ids):
    headers = {
        'Authorization': f'Bearer {token}'
    }
    widget_data = []
    for widget_id in widget_ids:
        response = requests.get(f'{base_url}/internal/widgets.get?id={widget_id}', headers=headers)
        if response.status_code == 200:
            widget_json = response.json()
            remove_dashboard_v1(widget_json)
            widget_data.append(widget_json)
        else:
            st.error(f'Failed to retrieve widget data for ID: {widget_id}. Status code: {response.status_code}')
            try:
                st.error(f"API Error: {response.json().get('error', 'Unknown error')}")  
            except ValueError:
                st.error("API Error: Could not decode JSON response")
    return widget_data

def update_widget_data(base_url, token, widget_data, search_text, replace_text):
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    updated_widget_data = []
    for widget in widget_data:
        widget_str = json.dumps(widget, separators=(',', ':'))
        if search_text in widget_str:
            updated_widget = widget_str.replace(search_text, replace_text)
            try:
                updated_widget_dict = json.loads(updated_widget)
                widget_id = updated_widget_dict['widget']['id']
            except (KeyError, json.JSONDecodeError) as e:
                st.error(f"Error processing widget: {e}. Widget data: {widget}")
                updated_widget_data.append(widget) 
                continue
            
            request_body = {
                "data_sources": updated_widget_dict['widget'].get("data_sources", []),
                "description": updated_widget_dict['widget'].get("description", ""),
                "id": updated_widget_dict['widget'].get("id", ""),
                "layout": updated_widget_dict['widget'].get("layout", []),
                "sub_widgets": updated_widget_dict['widget'].get("sub_widgets", []),
                "title": updated_widget_dict['widget'].get("title", "")
            }
            
            request_body_str = json.dumps(request_body, separators=(',', ':'))
            
            response = requests.post(f'{base_url}/internal/widgets.update', headers=headers, data=request_body_str)
            if response.status_code == 200:
                st.success(f'Widget with ID {widget_id} updated successfully')
                updated_widget_data.append(updated_widget_dict)
            else:
                st.error(f'Failed to update widget with ID: {widget_id}. Status code: {response.status_code}')
                try:
                    st.error(f"API Error: {response.json().get('error', 'Unknown error')}")
                except ValueError:
                    st.error("API Error: Could not decode JSON response")
        else:
            updated_widget_data.append(widget)
    return updated_widget_data

def main():
    st.title("Widget Data Update App")
    
    base_url = st.text_input('Enter the base URL (e.g., https://app.devrev.ai/api/gateway)')
    token = st.text_input('Enter the API token')
    widget_ids = st.text_input('Enter the widget IDs (comma-separated)').split(',')
    
    if st.button("Get Widget Data"):
        widget_data = get_widget_data(base_url, token, widget_ids)
        
        st.subheader("Input")
        st.json({"base_url": base_url, "token": token, "widget_ids": widget_ids})
        
        st.subheader("Widget Data from GET Call")
        for widget in widget_data:
            st.json(widget)
    
    search_text = st.text_input('Enter the text to search for')
    replace_text = st.text_input('Enter the text to replace with')
    
    if st.button("Update Widget Data"):
        updated_widget_data = update_widget_data(base_url, token, widget_data, search_text, replace_text)
        
        st.subheader("Input")
        st.json({"search_text": search_text, "replace_text": replace_text})
        
        st.subheader("Updated Widget Data")
        for widget in updated_widget_data:
            st.json(widget)

if __name__ == '__main__':
    main()
