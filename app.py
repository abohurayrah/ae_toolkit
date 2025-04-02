# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from supabase import create_client, Client
import math
import datetime
import traceback # For more detailed error logging if needed

# --- Page Configuration ---
st.set_page_config(
    page_title="AE Toolkit",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Initialize Supabase Client ---
@st.cache_resource # Use cache_resource for singleton-like behavior
def init_supabase_client():
    try:
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_KEY"]
        return create_client(supabase_url, supabase_key)
    except KeyError:
        st.error("Supabase credentials not found. Configure .streamlit/secrets.toml")
        st.stop()
    except Exception as e:
        st.error(f"Error initializing Supabase client: {e}")
        st.stop()

supabase: Client = init_supabase_client()

# --- Helper Functions ---
def format_currency(amount, currency="SAR"):
    if amount is None or not isinstance(amount, (int, float)): return "N/A"
    try:
        formatted = f"{amount:,.0f}"
        if currency and not formatted.endswith(currency) and not any(symbol in formatted for symbol in ['SAR', '$', '€', '£']):
             formatted += f" {currency}"
        return formatted
    except (ValueError, TypeError): return "N/A"

def format_percentage(value):
    if value is None or not isinstance(value, (int, float)): return "N/A"
    try: return f"{value:.1f}%"
    except (ValueError, TypeError): return "N/A"

def clean_number(num_str, is_percentage=False):
    if num_str is None: return 0.0
    if isinstance(num_str, (int, float)):
        val = float(num_str)
        # Treat percentage input '5' as 5%, not 0.05% unless it's already < 1
        return val / 100.0 if is_percentage and abs(val) >= 1 else val
    cleaned = str(num_str).replace(',', '').replace('%', '').strip()
    if not cleaned: return 0.0
    try:
        val = float(cleaned)
        return val / 100.0 if is_percentage else val
    except ValueError: return 0.0

# --- Authentication ---
def show_login_form():
    st.subheader("Login to AE Toolkit")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")
        if submit_button:
            if not email or not password: st.error("Email/Password required.")
            else:
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    if response.user and response.session:
                        st.session_state['user'] = response.user.dict()
                        st.session_state['session'] = response.session.dict()
                        st.success("Login successful!"); st.rerun()
                    else: st.error("Login failed. Check credentials.")
                except Exception as e: st.error(f"Login error: Invalid email or password.")

# --- Database Functions ---
def save_deal_bundle_to_db(user_id: str, session_token: str, deals_list: list) -> bool:
    if not deals_list: st.warning("No deals to save."); return False
    if not user_id: st.error("Critical Error: User ID missing."); return False
    if not session_token: st.error("Critical Error: Auth token missing."); return False
    prepared_deals=[]; skipped_count=0
    for deal in deals_list:
        db_deal = { "client_name": deal.get("client_name"), "deal_size": deal.get("deal_size"), "monthly_rate": deal.get("monthly_rate"), "admin_fee": deal.get("admin_fee"), "months": deal.get("months"), "monthly_profit": deal.get("monthly_profit"), "total_profit": deal.get("total_profit"), "admin_fee_amount": deal.get("admin_fee_amount"), "gross_profit": deal.get("gross_profit"), "user_id": user_id }
        if not all([ db_deal["client_name"], isinstance(db_deal.get("deal_size"), (int, float)) and db_deal["deal_size"] > 0, isinstance(db_deal.get("months"), int) and db_deal["months"] > 0, db_deal["user_id"] is not None ]):
             st.warning(f"Skipping '{db_deal.get('client_name', 'Unnamed')}' - missing/invalid."); skipped_count += 1; continue
        prepared_deals.append(db_deal)
    if not prepared_deals: st.error("No valid deals remaining."); return False
    if skipped_count > 0: st.warning(f"{skipped_count} deals skipped.")
    try:
        supabase.auth.set_session(access_token=session_token, refresh_token=st.session_state.get('session',{}).get('refresh_token', 'dummy'))
        response = supabase.table('deals').insert(prepared_deals).execute()
        if hasattr(response, 'error') and response.error: error_detail = response.error.message if hasattr(response.error, 'message') else str(response.error); st.error(f"DB error: {error_detail}"); return False
        elif not response.data: st.error("Bulk save failed: No data returned."); return False
        elif len(response.data) != len(prepared_deals): st.warning(f"Partial success: Saved {len(response.data)}/{len(prepared_deals)}."); return False
        else: return True
    except Exception as e: st.error(f"Exception during bulk save: {e}"); st.error(traceback.format_exc()); return False

def load_deals_from_db(user_id: str, session_token: str):
    if not user_id: return []
    if not session_token: st.error("Cannot load: Missing session token."); return []
    try:
        supabase.auth.set_session(access_token=session_token, refresh_token=st.session_state.get('session',{}).get('refresh_token', 'dummy'))
        response = supabase.table('deals').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
        if hasattr(response, 'error') and response.error: st.error(f"Error loading deals: {response.error.message}"); return []
        return response.data if response.data else []
    except Exception as e: st.error(f"Exception loading deals: {e}"); return []

def delete_deal_from_db(deal_id: str, user_id: str, session_token: str):
    if not user_id or not deal_id or not session_token: return False
    try:
        supabase.auth.set_session(access_token=session_token, refresh_token=st.session_state.get('session',{}).get('refresh_token', 'dummy'))
        response = supabase.table('deals').delete().match({'id': deal_id, 'user_id': user_id}).execute()
        if hasattr(response, 'error') and response.error: st.error(f"Error deleting deal {deal_id}: {response.error.message}"); return False
        return True
    except Exception as e: st.error(f"Exception deleting deal {deal_id}: {e}"); return False


# --- Calculator UI Functions ---

def credit_limit_calculator():
    """Renders the Credit Limit Calculator UI and handles calculations."""
    st.header("Credit Limit Calculator")
    st.caption("Calculate the credit limit based on financial data and industry type.")

    form_key = "cl_form"

    with st.form(form_key, clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            requested_limit_str = st.text_input("Requested Credit Limit (SAR)", placeholder="e.g., 1,500,000", key=f"{form_key}_cl_req_limit")
            revenue_str = st.text_input("Revenue (SAR)", placeholder="e.g., 10,000,000", key=f"{form_key}_cl_revenue")
            net_profit_percentage_str = st.text_input("Net Profit (% of Revenue)", placeholder="e.g., 5 or 5.5", key=f"{form_key}_cl_np_perc")
            st.markdown("**Current Ratio Components:**")
            current_assets_str = st.text_input("Current Assets (SAR)", placeholder="e.g., 3,000,000", key=f"{form_key}_cl_ca")
            current_liabilities_str = st.text_input("Current Liabilities (SAR)", placeholder="e.g., 1,500,000", key=f"{form_key}_cl_cl")
            exposure_outstanding_str = st.text_input("Exposure Outstanding (SAR)", placeholder="e.g., 2,000,000", key=f"{form_key}_cl_exposure")
        with c2:
            industry_type = st.selectbox("Industry Type", ["Trading", "Manufacturing", "Contractor"], index=None, placeholder="Select industry type", key=f"{form_key}_cl_industry")
            unbilled_revenue_str = ""
            if industry_type == "Contractor":
                unbilled_revenue_str = st.text_input("Unbilled Revenue (SAR)", placeholder="e.g., 500,000", key=f"{form_key}_cl_unbilled")
            is_saudi = st.radio("Main Shareholders Saudi?", ["Yes", "No"], index=0, key=f"{form_key}_cl_saudi", horizontal=True)
            years_of_operation_str = st.number_input("Years of Operation", min_value=0.1, step=0.5, value=1.0, format="%.1f", key=f"{form_key}_cl_years_op")
            has_concentration = st.radio("Customer Concentration (>40% Revenue)?", ["No", "Yes"], index=0, key=f"{form_key}_cl_concentration", horizontal=True)
            number_of_projects_str = st.number_input("Number of Active Projects", min_value=1, step=1, value=1, key=f"{form_key}_cl_projects")
            has_previous_payments = st.radio("Previous Payments to BuildNow?", ["No", "Yes"], index=0, key=f"{form_key}_cl_prev_pay", horizontal=True)
            has_payment_delays = st.radio("Payment Delays > 30 Days (if any previous)?", ["No", "Yes"], index=0, key=f"{form_key}_cl_pay_delay", horizontal=True)

        submitted = st.form_submit_button("Calculate Credit Limit")

    if submitted:
        try:
            # --- Data Cleaning ---
            requested_limit = clean_number(requested_limit_str)
            revenue = clean_number(revenue_str)
            net_profit_percentage = clean_number(net_profit_percentage_str, is_percentage=True)
            current_assets = clean_number(current_assets_str)
            current_liabilities = clean_number(current_liabilities_str)
            exposure_outstanding = clean_number(exposure_outstanding_str)
            unbilled_revenue = clean_number(unbilled_revenue_str) if industry_type == "Contractor" else 0
            years_of_operation = clean_number(years_of_operation_str)
            number_of_projects = int(clean_number(number_of_projects_str))

            # --- Validation ---
            errors = []
            if requested_limit <= 0: errors.append("Requested Limit > 0.")
            if revenue <= 0: errors.append("Revenue > 0.")
            if exposure_outstanding < 0: errors.append("Exposure >= 0.")
            if not industry_type: errors.append("Industry Type required.")
            if industry_type == "Contractor":
                if unbilled_revenue_str is None or unbilled_revenue_str.strip() == "": errors.append("Unbilled Revenue required.")
                elif unbilled_revenue <= 0: errors.append("Unbilled Revenue > 0.")
            if years_of_operation <= 0: errors.append("Years Op > 0.")
            if number_of_projects < 1: errors.append("Projects >= 1.")
            if net_profit_percentage_str is None or net_profit_percentage_str.strip() == "": errors.append("Net Profit % required.")
            elif net_profit_percentage <= 0: errors.append("Net Profit % must be > 0.")
            actual_net_profit = revenue * net_profit_percentage if revenue > 0 else 0
            actual_current_ratio = None
            if current_assets_str is None or current_assets_str.strip() == "": errors.append("Current Assets required.")
            if current_liabilities_str is None or current_liabilities_str.strip() == "": errors.append("Current Liabilities required.")
            if current_assets <= 0: errors.append("Current Assets > 0.")
            if current_liabilities <= 0: errors.append("Current Liabilities > 0.")
            if current_liabilities > 0 and current_assets > 0: actual_current_ratio = current_assets / current_liabilities # Calculate CR here
            if errors: st.error("Input Errors:\n" + "\n".join([f"- {e}" for e in errors])); return

            # --- Eligibility ---
            eligibility_reasons = []
            is_eligible = True
            if actual_net_profit <= 0: eligibility_reasons.append("Net profit > 0% required."); is_eligible = False
            # Check calculated CR for eligibility
            if actual_current_ratio is None: eligibility_reasons.append("Valid Current Assets/Liabilities needed."); is_eligible = False
            elif actual_current_ratio <= 1: eligibility_reasons.append(f"Current ratio > 1 required (is {actual_current_ratio:.2f})."); is_eligible = False
            if not is_eligible: st.error("Not Eligible:\n" + "\n".join([f"- {r}" for r in eligibility_reasons])); return

            # --- Calculation ---
            st.success("Eligible for Credit Calculation")
            calculation_details={"Base Limit Calculation":"","Base Limit Cap Applied":"","Adjustments":[],"Final Limit":0,"Min/Max Applied":""}
            max_initial_base_limit=2000000
            base_limit_unadjusted=unbilled_revenue*0.15 if industry_type=="Contractor" else revenue*0.05
            calculation_details["Base Limit Calculation"]=f"15% Unbilled ({format_currency(unbilled_revenue)}) = {format_currency(base_limit_unadjusted)}" if industry_type=="Contractor" else f"5% Revenue ({format_currency(revenue)}) = {format_currency(base_limit_unadjusted)}"
            credit_limit=min(base_limit_unadjusted,max_initial_base_limit)
            if base_limit_unadjusted>max_initial_base_limit: calculation_details["Base Limit Cap Applied"]=f"Initial base capped at {format_currency(max_initial_base_limit)}"
            base_limit_after_cap=credit_limit

            # <<< FIX: Adjustment Function and Logic >>>
            def apply_adjustment(current_limit, factor, reason, value_info=""):
                """Applies adjustment factor and stores formatted detail string."""
                change_percent = (factor - 1) * 100
                new_limit = current_limit * factor
                reason_full = f"{reason} {value_info}".strip()
                # Format the detail string exactly as needed for output
                detail_str = f"{reason_full}: {change_percent:+.0f}% ({format_currency(current_limit)} -> {format_currency(new_limit)})"
                calculation_details["Adjustments"].append(detail_str) # Store the formatted string
                return new_limit

            # Apply adjustments sequentially
            # Negative
            if exposure_outstanding > revenue*0.3: credit_limit=apply_adjustment(credit_limit,0.65,"Exposure > 30% Revenue")
            if is_saudi=="No": credit_limit=apply_adjustment(credit_limit,0.90,"Non-Saudi company")
            if years_of_operation<3: credit_limit=apply_adjustment(credit_limit,0.90,"Company < 3 years old")
            if has_concentration=="Yes": credit_limit=apply_adjustment(credit_limit,0.90,"Customer concentration > 40%")
            if has_previous_payments=="Yes" and has_payment_delays=="Yes": credit_limit=apply_adjustment(credit_limit,0.90,"Payment delays > 30 days")
            if number_of_projects<3: credit_limit=apply_adjustment(credit_limit,0.95,"Number of Projects < 3")
            # Positive (use the calculated actual_current_ratio)
            if actual_current_ratio > 2: credit_limit=apply_adjustment(credit_limit,1.05,f"Current Ratio > 2",f"({actual_current_ratio:.2f})")
            if years_of_operation>10: credit_limit=apply_adjustment(credit_limit,1.05,"Years in Business > 10")
            if has_previous_payments=="Yes" and has_payment_delays=="No": credit_limit=apply_adjustment(credit_limit,1.10,"Previous Timely Payments")
            # <<< END FIX >>>

            adjusted_limit=credit_limit
            min_final_limit=100000; max_final_limit=2000000; final_limit=credit_limit
            if final_limit<min_final_limit: final_limit=min_final_limit; calculation_details["Min/Max Applied"]=f"Floor Applied: {format_currency(min_final_limit)}"
            elif final_limit>max_final_limit:
                 if not (calculation_details["Base Limit Cap Applied"] and max_final_limit==max_initial_base_limit): final_limit=max_final_limit; calculation_details["Min/Max Applied"]=f"Ceiling Applied: {format_currency(max_final_limit)}"
            calculation_details["Final Limit"]=final_limit

            # --- Display Results ---
            st.subheader("Calculation Results")
            col1, col2 = st.columns(2)
            with col1: st.metric("Requested Limit", format_currency(requested_limit))
            with col2: st.metric("Maximum Calculated Limit", format_currency(final_limit), delta_color="off")
            additional = 0
            if final_limit >= requested_limit:
                st.success(f"Calculated limit covers requested amount.")
                additional = final_limit - requested_limit
                if additional > 0: st.info(f"Additional available: {format_currency(additional)}")
            else:
                st.warning(f"Calculated limit ({format_currency(final_limit)}) is less than requested.")
                st.error(f"Shortfall: {format_currency(requested_limit - final_limit)}")

            # --- <<< FIX: Display Breakdown Correctly >>> ---
            with st.expander("Show Calculation Breakdown", expanded=True):
                st.write(f"**1. Base Limit:** {calculation_details['Base Limit Calculation']}")
                if calculation_details['Base Limit Cap Applied']: st.write(f"   - {calculation_details['Base Limit Cap Applied']}")
                st.write(f"   *(Base used for adjustments: {format_currency(base_limit_after_cap)})*")
                st.divider()
                st.write("**2. Adjustments (Sequential):**")
                if calculation_details["Adjustments"]:
                    # Iterate through the stored strings and display them
                    for adj_detail_str in calculation_details["Adjustments"]:
                        st.write(f"- {adj_detail_str}")
                else:
                    st.write("- None")
                st.write(f"   *(Limit after adjustments: {format_currency(adjusted_limit)})*")
                st.divider()
                st.write("**3. Final Thresholds:**")
                if calculation_details["Min/Max Applied"]: st.write(f"- {calculation_details['Min/Max Applied']}")
                else: st.write("- No final floor/ceiling applied.")
                st.markdown(f"**Final Calculated Credit Limit: {format_currency(calculation_details['Final Limit'])}**")
            # --- <<< END FIX >>> ---

        except ZeroDivisionError: st.error("Calc error: Division by zero (Check Current Liabilities).")
        except Exception as e: st.error(f"Unexpected error: {e}"); st.error(traceback.format_exc())

    # --- <<< FIX: Display Correct Rules >>> ---
    st.divider()
    with st.expander("Calculation Rules Overview", expanded=False):
         st.markdown("""
         **Base Credit Limit**
         *   Trading/Manufacturing: 5% of Revenue
         *   Contractor: 15% of Unbilled Revenue
         *   *(Initial Base Limit capped at 2,000,000 SAR)*

         **Negative Adjustments (Applied Sequentially)**
         *   Exposure > 30% of Revenue: -35%
         *   Non-Saudi company: -10%
         *   Company < 3 years old: -10%
         *   Customer concentration > 40%: -10%
         *   Payment delays > 30 days (if prev. payments exist): -10%
         *   Number of Projects < 3: -5%

         **Positive Adjustments (Applied Sequentially)**
         *   Current Ratio > 2: +5%
         *   Years in Business > 10: +5%
         *   Previous Timely Payments (no delays, if prev. payments exist): +10%

         **Limits (Applied Finally)**
         *   Minimum Credit Limit: 100,000 SAR
         *   Maximum Credit Limit: 2,000,000 SAR
         """)
    # --- <<< END FIX >>> ---


# --- profit_calculator Function ---
# (Keep the previously corrected version - no changes requested here)
def profit_calculator(user_id, session_token):
    st.header("Profitability Calculator")
    st.caption("Add deals to staging, calculate staged profit, save bundle. View/manage saved deals.")
    if 'unsaved_deals' not in st.session_state: st.session_state.unsaved_deals = []
    with st.expander("Add New Deal to Staging", expanded=True):
        with st.form("add_deal_form", clear_on_submit=False): # Keep form populated
            c1,c2,c3=st.columns(3);
            with c1: client_name=st.text_input("Client",key="pc_cn"); deal_size=st.number_input("Size(SAR)",min_value=.01,format="%.0f",key="pc_ds");
            with c2: monthly_rate=st.number_input("Rate(%)",min_value=.1,value=3.0,format="%.1f",key="pc_mr"); admin_fee_perc=st.number_input("Fee(%)",min_value=0.0,value=1.5,format="%.1f",key="pc_af");
            with c3: months=st.number_input("Months",min_value=1,value=4,key="pc_m");
            submitted=st.form_submit_button("Add to Unsaved Deals");
            if submitted:
                if not client_name or deal_size<=0: st.warning("Client & Size required.")
                else:
                    monthly_profit=deal_size*(monthly_rate/100.0); total_profit=monthly_profit*months; admin_fee_amount=deal_size*(admin_fee_perc/100.0); gross_profit=total_profit+admin_fee_amount; temp_id=datetime.datetime.now().isoformat()+"_"+client_name.replace(" ","_")
                    new_deal={"temp_id":temp_id,"client_name":client_name,"deal_size":deal_size,"monthly_rate":monthly_rate,"admin_fee":admin_fee_perc,"months":months,"monthly_profit":monthly_profit,"total_profit":total_profit,"admin_fee_amount":admin_fee_amount,"gross_profit":gross_profit}
                    st.session_state.unsaved_deals.append(new_deal)
                    st.success(f"Deal '{client_name}' staged. Modify inputs to add another.")
    st.divider()
    st.subheader("Unsaved Deals (Staging Area)")
    unsaved_deals_list = st.session_state.get('unsaved_deals', [])
    if not unsaved_deals_list: st.info("No deals currently staged.")
    else:
        unsaved_df = pd.DataFrame(unsaved_deals_list)
        display_unsaved_df = unsaved_df[['temp_id', 'client_name', 'deal_size', 'monthly_rate', 'admin_fee', 'months', 'gross_profit']].copy()
        display_unsaved_df['Deal Size (SAR)']=display_unsaved_df['deal_size'].apply(lambda x: format_currency(x,"")); display_unsaved_df['Monthly Rate']=display_unsaved_df['monthly_rate'].apply(format_percentage); display_unsaved_df['Admin Fee %']=display_unsaved_df['admin_fee'].apply(format_percentage); display_unsaved_df['Gross Profit (SAR)']=display_unsaved_df['gross_profit'].apply(lambda x: format_currency(x,"")); display_unsaved_df['Months']=display_unsaved_df['months'].astype(int);display_unsaved_df['Client Name']=display_unsaved_df['client_name']
        display_unsaved_df['Remove']=False
        unsaved_editor_cols = ['Client Name', 'Deal Size (SAR)', 'Monthly Rate', 'Admin Fee %', 'Months', 'Gross Profit (SAR)', 'Remove']
        with st.form("remove_staged_deals_form"):
            st.write("Review staged deals. Select 'Remove' checkbox and submit below.")
            edited_unsaved_df = st.data_editor(display_unsaved_df[unsaved_editor_cols], column_config={"Remove": st.column_config.CheckboxColumn("Remove?", default=False)}, disabled=['Client Name', 'Deal Size (SAR)', 'Monthly Rate', 'Admin Fee %', 'Months', 'Gross Profit (SAR)'], use_container_width=True, hide_index=True, key="unsaved_deals_editor")
            remove_button = st.form_submit_button("Remove Selected Staged Deals")
            if remove_button:
                selected_to_remove_indices = edited_unsaved_df[edited_unsaved_df['Remove'] == True].index
                if not selected_to_remove_indices.empty:
                    temp_ids_to_remove = unsaved_df.loc[selected_to_remove_indices, 'temp_id'].tolist()
                    st.session_state.unsaved_deals = [d for d in unsaved_deals_list if d.get('temp_id') not in temp_ids_to_remove]
                    st.success(f"Removed {len(temp_ids_to_remove)} deals."); st.rerun()
                else: st.warning("No deals selected for removal.")
        st.write("**Staging Area Summary:**")
        if not unsaved_df.empty:
            staged_total_size = pd.to_numeric(unsaved_df['deal_size'], errors='coerce').fillna(0).sum()
            staged_total_gp = pd.to_numeric(unsaved_df['gross_profit'], errors='coerce').fillna(0).sum()
            summary_cols_staged = st.columns(2)
            with summary_cols_staged[0]: st.metric("Total Staged Deal Size", format_currency(staged_total_size))
            with summary_cols_staged[1]: st.metric("Total Staged Gross Profit", format_currency(staged_total_gp))
        else: st.info("Add deals to see staging summary.")
        st.divider()
        if st.button("Save All Staged Deals to Database", type="primary", key="save_bundle_btn"):
            current_staged_deals = st.session_state.get('unsaved_deals', [])
            num_to_save = len(current_staged_deals)
            if num_to_save > 0:
                if not session_token: st.error("Session token missing.")
                else:
                    with st.spinner(f"Saving {num_to_save} deals..."): success = save_deal_bundle_to_db(user_id, session_token, current_staged_deals)
                    if success: st.success(f"Saved {num_to_save} deals."); st.session_state.unsaved_deals = []; st.rerun()
                    else: st.error("Failed to save bundle. Deals remain staged.")
            else: st.warning("No deals in staging to save.")
    st.divider()
    st.subheader("Saved Deals (From Database)")
    if not session_token: st.warning("Session token missing. Cannot load.")
    else:
        with st.spinner("Loading saved deals..."): saved_deals_data = load_deals_from_db(user_id, session_token)
        if not saved_deals_data: st.info("No deals saved yet.")
        else:
            try:
                deals_df = pd.DataFrame(saved_deals_data)
                if deals_df.empty: st.info("No deals data found."); return
                required_summary_cols = ['deal_size', 'gross_profit', 'monthly_rate']
                if not all(col in deals_df.columns for col in required_summary_cols): st.error("Loaded data missing summary columns."); return
                deals_df['deal_size'] = pd.to_numeric(deals_df['deal_size'], errors='coerce').fillna(0)
                deals_df['gross_profit'] = pd.to_numeric(deals_df['gross_profit'], errors='coerce').fillna(0)
                deals_df['monthly_rate'] = pd.to_numeric(deals_df['monthly_rate'], errors='coerce')
                required_display_cols=['id','created_at','client_name','deal_size','monthly_rate','admin_fee','months','gross_profit']
                if not all(col in deals_df.columns for col in required_display_cols): st.error("Loaded data missing display columns."); return
                display_df=deals_df[required_display_cols].copy()
                display_df['Saved On']=pd.to_datetime(display_df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
                display_df['Deal Size (SAR)']=deals_df['deal_size'].apply(lambda x: format_currency(x,"") if pd.notna(x) else "N/A")
                display_df['Monthly Rate']=deals_df['monthly_rate'].apply(lambda x: format_percentage(x) if pd.notna(x) else "N/A")
                display_df['Admin Fee %']=pd.to_numeric(deals_df['admin_fee'], errors='coerce').apply(lambda x: format_percentage(x) if pd.notna(x) else "N/A")
                display_df['Gross Profit (SAR)']=deals_df['gross_profit'].apply(lambda x: format_currency(x,"") if pd.notna(x) else "N/A")
                display_df['Months']=pd.to_numeric(deals_df['months'],errors='coerce').fillna(0).astype(int)
                display_df['Client Name']=deals_df['client_name']
                editor_cols=['Saved On','Client Name','Deal Size (SAR)','Monthly Rate','Admin Fee %','Months','Gross Profit (SAR)']
                display_for_editor=display_df[editor_cols].copy();display_for_editor['Delete']=False
                with st.form("delete_saved_deals_form"):
                    st.write("View/select saved deals to delete:")
                    edited_df=st.data_editor(display_for_editor,column_config={"Delete":st.column_config.CheckboxColumn("Del?",default=False)},disabled=editor_cols,use_container_width=True,hide_index=True,key="saved_deals_editor")
                    delete_button=st.form_submit_button("Delete Selected Saved")
                    if delete_button:
                        selected_indices=edited_df[edited_df['Delete']==True].index
                        if not selected_indices.empty:
                            deals_to_delete_ids=deals_df.loc[selected_indices,'id'].tolist()
                            deleted_count=0;total_to_delete=len(deals_to_delete_ids)
                            with st.spinner(f"Deleting {total_to_delete}..."):results=[delete_deal_from_db(did,user_id,session_token) for did in deals_to_delete_ids];deleted_count=sum(results)
                            if deleted_count>0: st.success(f"Deleted {deleted_count}/{total_to_delete}.")
                            if deleted_count<total_to_delete: st.warning(f"Failed to delete {total_to_delete-deleted_count}.")
                            st.rerun()
                        else: st.warning("No deals selected.")
                st.divider()
                st.subheader("Summary of Saved Deals")
                if all(col in deals_df.columns for col in ['deal_size', 'gross_profit', 'monthly_rate']):
                     total_saved_deal_size = deals_df['deal_size'].sum(skipna=True)
                     total_saved_gross_profit = deals_df['gross_profit'].sum(skipna=True)
                     average_saved_monthly_rate = deals_df['monthly_rate'].mean(skipna=True) if deals_df['monthly_rate'].notna().any() else 0
                     summary_cols=st.columns(3)
                     with summary_cols[0]: st.metric("Total Deal Size (Saved)", format_currency(total_saved_deal_size))
                     with summary_cols[1]: st.metric("Total Gross Profit (Saved)", format_currency(total_saved_gross_profit))
                     with summary_cols[2]: st.metric("Avg Monthly Rate (Saved)", format_percentage(average_saved_monthly_rate))
                else: st.warning("Cannot calculate summary - cols missing.")
                csv_data = display_for_editor.drop(columns=['Delete']).to_csv(index=False).encode('utf-8')
                st.download_button("Download Saved Deals as CSV", csv_data, 'ae_saved_deals.csv', 'text/csv')
            except Exception as e: st.error(f"Error processing saved deals: {e}"); st.error(traceback.format_exc())


# --- murabahah_calculator Function ---
# (Keep the previously corrected version)
def murabahah_calculator():
    st.header("Murabahah Size Calculator")
    st.caption("Calculate profitability and payment schedule (Admin fee paid in Month 1).")
    st.subheader("Inputs")
    deal_size = st.number_input("Deal Size (SAR)", min_value=0.01, value=100000.0, step=10000.0, format="%.0f", key="mur_deal_size")
    profit_rate = st.slider("Monthly Profit Rate (%)", 1.0, 5.0, 2.5, 0.1, format="%.1f%%", key="mur_profit_rate")
    financing_period_float = st.slider("Financing Period (Months)", 1.0, 12.0, 3.0, 1.0, key="mur_period")
    financing_period = int(financing_period_float)
    admin_fee_perc = st.slider("Administrative Fee (%)", 0.0, 5.0, 1.5, 0.1, format="%.1f%%", key="mur_admin_fee")
    st.divider()
    st.subheader("Murabahah Summary & Schedule")
    total_profit = 0; total_admin_fee = 0; total_earnings = 0
    first_month_payment = 0; subsequent_monthly_payment = 0
    payment_schedule_df = pd.DataFrame()
    if deal_size > 0 and financing_period > 0:
        try:
            admin_fee_amount = deal_size * (admin_fee_perc / 100.0)
            monthly_profit_rate_dec = profit_rate / 100.0
            total_profit_amount = deal_size * monthly_profit_rate_dec * financing_period
            total_earnings = total_profit_amount + admin_fee_amount
            total_admin_fee = admin_fee_amount
            base_repayment_per_month = (deal_size + total_profit_amount) / financing_period if financing_period > 0 else 0
            first_month_payment = base_repayment_per_month + admin_fee_amount
            subsequent_monthly_payment = base_repayment_per_month
            schedule = []; remaining_principal = deal_size
            for month in range(1, financing_period + 1):
                 profit_for_month = remaining_principal * monthly_profit_rate_dec
                 current_month_total_payment = first_month_payment if month == 1 else subsequent_monthly_payment
                 admin_fee_paid_this_month = admin_fee_amount if month == 1 else 0
                 principal_paid = max(0, current_month_total_payment - profit_for_month - admin_fee_paid_this_month)
                 if month == financing_period: principal_paid = remaining_principal
                 remaining_principal -= principal_paid
                 schedule.append({"Month": month,"Installment (SAR)": current_month_total_payment,"Principal (SAR)": principal_paid,"Profit (SAR)": profit_for_month,"Admin Fee Paid (SAR)": admin_fee_paid_this_month,"Remaining Principal (SAR)": max(0, remaining_principal)})
            if schedule: payment_schedule_df = pd.DataFrame(schedule)
        except Exception as e: st.error(f"Error in Murabahah calc: {e}")
    summary_cols = st.columns(4)
    with summary_cols[0]: st.metric("First Month Payment", format_currency(first_month_payment))
    with summary_cols[1]: st.metric("Subsequent Payments", format_currency(subsequent_monthly_payment))
    with summary_cols[2]: st.metric("Total Profit", format_currency(total_profit))
    with summary_cols[3]: st.metric("Total Earnings", format_currency(total_earnings), delta_color="off")
    st.write("")
    st.write("**Payment Schedule**")
    if not payment_schedule_df.empty:
        format_cols=["Installment (SAR)","Principal (SAR)","Profit (SAR)","Admin Fee Paid (SAR)","Remaining Principal (SAR)"]
        st.dataframe(payment_schedule_df.style.format("{:,.0f}",subset=[c for c in format_cols if c in payment_schedule_df]),hide_index=True,use_container_width=True)
    else: st.info("Enter positive Deal Size & Period.")

# --- Main Application Flow ---
# (Initialization and Auth Check remain the same)
if 'user' not in st.session_state: st.session_state['user'] = None
if 'session' not in st.session_state: st.session_state['session'] = None
if 'unsaved_deals' not in st.session_state: st.session_state['unsaved_deals'] = []

if not st.session_state.user or not st.session_state.session:
    show_login_form()
else:
    user_info = st.session_state.get('user', {}); session_info = st.session_state.get('session', {})
    user_email = user_info.get('email', 'Unknown'); user_id = user_info.get('id')
    access_token = session_info.get('access_token')
    # Header
    header_cols = st.columns([0.85, 0.15])
    with header_cols[0]: st.title("AE Toolkit"); st.caption(f"User: {user_email}")
    with header_cols[1]:
        if st.button("Logout", key="logout_btn"):
            try:
                supabase.auth.sign_out(); keys_to_clear=list(st.session_state.keys()); [st.session_state.pop(key) for key in keys_to_clear]
                st.success("Logged out."); st.rerun()
            except Exception as e: st.error(f"Logout error: {e}")
    # Main Content Check
    if not user_id: st.error("User ID missing. Re-login."); st.stop()
    if not access_token: st.warning("Session token missing. DB actions may fail.")
    # Tabs
    tab_titles = ["💳 Credit Limit", "💰 Profitability", "📊 Murabahah Size"]
    tab1, tab2, tab3 = st.tabs(tab_titles)
    with tab1: credit_limit_calculator()
    with tab2: profit_calculator(user_id, access_token)
    with tab3: murabahah_calculator()