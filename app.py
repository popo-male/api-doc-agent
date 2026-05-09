import streamlit as st
import time

# Import your core agent logic
from agents.workflow import run_agent

# ==========================================
# 1. PAGE CONFIGURATION & CUSTOM CSS
# ==========================================
st.set_page_config(
    page_title="API Doc Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS to hide Streamlit branding and make buttons pop
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stButton>button {
        background-color: #4F46E5;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #4338CA;
        border-color: #4338CA;
        color: white;
    }
    .main-header {
        font-size: 4rem;
        font-weight: 800;
        margin-bottom: -10px;
    }
    .sub-header {
        color: #6B7280;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# 2. SIDEBAR (BYOK & Settings)
# ==========================================
with st.sidebar:
    st.header("⚙️ Configuration")
    st.markdown("To run the agents, you need a Google Gemini API key.")
    user_api_key = st.text_input(
        "Gemini API Key", type="password", placeholder="AIzaSy..."
    )
    st.caption("🔗 [Get a free API key here](https://aistudio.google.com/app/apikey)")

    st.divider()

    with st.expander("📚 Supported Formats"):
        st.markdown("""
        * **Swagger 2.0** (JSON/YAML)
        * **OpenAPI 3.0** (JSON/YAML)
        * **SOAP WSDL** (XML)
        """)

# ==========================================
# 3. MAIN UI
# ==========================================
st.title("🤖 API Documentation Agent")
st.markdown(
    '<p class="sub-header">Upload a raw API specification and let the AI Agents generate clean, standardized Markdown documentation.</p>',
    unsafe_allow_html=True,
)

# Use Tabs instead of Radio buttons for a much cleaner look
tab1, tab2 = st.tabs(["📂 Upload File", "🧾 Paste Raw Text"])

raw_content = ""

with tab1:
    uploaded_file = st.file_uploader(
        "Drag and drop your API spec here",
        type=["json", "yaml", "yml", "xml", "wsdl"],
    )
    if uploaded_file is not None:
        raw_content = uploaded_file.getvalue().decode("utf-8")

with tab2:
    pasted_text = st.text_area(
        "Paste raw JSON, YAML, or XML here:",
        height=300,
        label_visibility="collapsed",
        placeholder="Paste your Swagger/WSDL code here...",
    )
    if pasted_text:
        raw_content = pasted_text

# ==========================================
# 4. EXECUTION TRIGGER
# ==========================================
st.write("")  # Spacer
if st.button("🚀 Generate Documentation", use_container_width=True):
    # Safety Checks
    if not user_api_key:
        st.error("🔑 Please enter your Gemini API Key in the sidebar.")
        st.stop()

    if not raw_content.strip():
        st.warning(
            "⚠️ Please provide an API specification by uploading a file or pasting text."
        )
        st.stop()

    # The Progress UI (Expandable Status Box)
    with st.status(
        "⏳ Agents are analyzing the specification...", expanded=True
    ) as status_box:
        log_output = st.empty()

        def ui_progress_callback(msg):
            log_output.info(f"**Action:** {msg}")  # Using info box for cleaner logs

        try:
            final_markdown = run_agent(
                raw_content=raw_content,
                progress_callback=ui_progress_callback,
                api_key=user_api_key,
            )

            status_box.update(
                label="✅ Documentation Generated Successfully!",
                state="complete",
                expanded=False,
            )
            st.session_state["generated_docs"] = final_markdown

            # Fun UI celebration!
            st.toast("Documentation ready!", icon="🎉")

        except Exception as e:
            status_box.update(
                label="❌ Agent Workflow Failed", state="error", expanded=True
            )
            st.error(f"An error occurred: {str(e)}")

# ==========================================
# 5. RESULTS DISPLAY
# ==========================================
if "generated_docs" in st.session_state:
    st.divider()

    col1, col2 = st.columns([8, 2])
    with col1:
        st.subheader("📄 Generated Documentation")
    with col2:
        st.download_button(
            label="⬇️ Download .md",
            data=st.session_state["generated_docs"],
            file_name="api_documentation.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # Wrap the output in a clean container so it doesn't bleed to the edges
    with st.container(border=True):
        st.markdown(st.session_state["generated_docs"])
