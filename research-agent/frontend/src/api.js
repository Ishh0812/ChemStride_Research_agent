const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Mirrors the backend's own COUNTRY_PROFILES/MENU_ORDER so the form still
// works if /countries can't be reached.
export const FALLBACK_COUNTRIES = [
  { code: 'IN', name: 'India', dial_code: '+91' },
  { code: 'CN', name: 'China', dial_code: '+86' },
  { code: 'US', name: 'United States', dial_code: '+1' },
  { code: 'DE', name: 'Germany', dial_code: '+49' },
  { code: 'AE', name: 'United Arab Emirates', dial_code: '+971' },
  { code: 'VN', name: 'Vietnam', dial_code: '+84' },
  { code: 'KR', name: 'South Korea', dial_code: '+82' },
  { code: 'JP', name: 'Japan', dial_code: '+81' },
]

async function parseErrorDetail(response) {
  let detail = `Request failed with status ${response.status}.`
  try {
    const body = await response.json()
    if (body?.detail) detail = body.detail
  } catch {
    // No JSON body to read — keep the generic message.
  }
  return detail
}

/**
 * Calls GET /countries on the FastAPI backend for the country dropdown.
 * Falls back to a static list (kept in sync with the backend's own
 * COUNTRY_PROFILES) if the request fails for any reason.
 */
export async function getCountries() {
  try {
    const response = await fetch(`${API_BASE_URL}/countries`)
    if (!response.ok) return FALLBACK_COUNTRIES
    const data = await response.json()
    return Array.isArray(data) && data.length ? data : FALLBACK_COUNTRIES
  } catch {
    return FALLBACK_COUNTRIES
  }
}

/**
 * Calls POST /research on the FastAPI backend and returns the parsed
 * JSON result produced by research_company(). Throws an Error with a
 * user-facing message on any non-2xx response or network failure.
 */
export async function researchCompany({ companyName, country, industryHint }) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}/research`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: companyName,
        country,
        industry_hint: industryHint || null,
        include_linkedin: true,
      }),
    })
  } catch {
    throw new Error(
      'Could not reach the research API. Is the FastAPI backend running on ' +
        `${API_BASE_URL}?`,
    )
  }

  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }

  return response.json()
}
