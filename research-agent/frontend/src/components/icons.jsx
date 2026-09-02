// Minimal inline icon set so the project has zero icon-library dependency.
const common = {
  width: 16,
  height: 16,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

export const GlobeIcon = () => (
  <svg {...common}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3c2.5 2.7 3.8 6 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-6-3.8-9S9.5 5.7 12 3Z" />
  </svg>
)

export const MailIcon = () => (
  <svg {...common}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m4 7 8 6 8-6" />
  </svg>
)

export const PhoneIcon = () => (
  <svg {...common}>
    <path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1.2 1.2 0 0 1 1.2-.3c1.3.4 2.7.6 4.1.6a1.2 1.2 0 0 1 1.2 1.2V20a1.2 1.2 0 0 1-1.2 1.2C10.6 21.2 2.8 13.4 2.8 3.2A1.2 1.2 0 0 1 4 2h3.3a1.2 1.2 0 0 1 1.2 1.2c0 1.4.2 2.8.6 4.1a1.2 1.2 0 0 1-.3 1.2Z" />
  </svg>
)

export const WhatsAppIcon = () => (
  <svg {...common}>
    <path d="M12 21a9 9 0 1 0-7.8-4.5L3 21l4.6-1.2A9 9 0 0 0 12 21Z" />
    <path d="M8.5 8.7c.2-.5.4-.5.7-.5h.5c.2 0 .4 0 .6.5s.7 1.7.7 1.8.1.3 0 .5-.2.3-.4.5-.4.4-.2.7c.2.3.9 1.5 2 2.4 1.3 1.1 2.1 1.3 2.4 1.4s.5 0 .7-.2.8-.9 1-1.2.5-.2.7-.1l1.6.8c.2.1.4.2.4.4s0 1-.4 1.5-1.5 1.1-2.6 1.1c-2.5 0-5.4-1.8-7.2-4.5-.7-1-1.1-2.2-1.1-3.3 0-1 .4-1.6.7-1.9Z" />
  </svg>
)

export const PersonIcon = () => (
  <svg {...common}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20c1.2-3.5 4-5.2 7-5.2s5.8 1.7 7 5.2" />
  </svg>
)

export const BadgeIcon = () => (
  <svg {...common}>
    <circle cx="12" cy="9" r="5" />
    <path d="m8 13.5-1.5 7L12 18l5.5 2.5-1.5-7" />
  </svg>
)

export const PinIcon = () => (
  <svg {...common}>
    <path d="M12 21s7-6.3 7-11.5A7 7 0 0 0 5 9.5C5 14.7 12 21 12 21Z" />
    <circle cx="12" cy="9.5" r="2.3" />
  </svg>
)

export const IndustryIcon = () => (
  <svg {...common}>
    <path d="M3 21V10l6 4v-4l6 4v-4l6 4v7H3Z" />
    <path d="M7 21v-4M12 21v-4M17 21v-4" />
  </svg>
)

export const ExternalLinkIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
)

export const WeChatIcon = () => (
  <svg {...common}>
    <path d="M9 11c-3.3 0-6 2.1-6 4.8 0 1.5.9 2.9 2.3 3.8l-.6 1.9 2.2-1.1c.6.2 1.3.3 2 .3h.3a5 5 0 0 1-.2-1.4c0-2.9 2.9-5.3 6.4-5.3h.3C15.1 11.9 12.3 11 9 11Z" />
    <path d="M21 16.4c0-2.2-2.3-4-5.1-4-2.8 0-5.1 1.8-5.1 4s2.3 4 5.1 4c.6 0 1.1-.1 1.6-.2l1.8.9-.5-1.6c1.3-.7 2.2-1.8 2.2-3.1Z" />
    <circle cx="7" cy="9.2" r="0.9" fill="currentColor" stroke="none" />
    <circle cx="11" cy="9.2" r="0.9" fill="currentColor" stroke="none" />
  </svg>
)

export const MapPinIcon = () => (
  <svg {...common}>
    <path d="M12 21s7-6.3 7-11.5A7 7 0 0 0 5 9.5C5 14.7 12 21 12 21Z" />
    <circle cx="12" cy="9.5" r="2.3" />
  </svg>
)

export const LanguageIcon = () => (
  <svg {...common}>
    <path d="M4 6h9M8.5 4v2.5M6 6c0 3.5 2 6 5 7.5M11 6c-.6 3.5-2.8 6.5-6 8.3" />
    <path d="M14 21l3.5-8L21 21M15.1 18h4.8" />
  </svg>
)

export const SunIcon = () => (
  <svg {...common}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2.2M12 19.8V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.2M19.8 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6" />
  </svg>
)

export const MoonIcon = () => (
  <svg {...common}>
    <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.8 6.8 0 0 0 10.5 10.5Z" />
  </svg>
)

export const SparklesIcon = () => (
  <svg {...common}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2" />
    <path d="M12 8l1.2 2.8L16 12l-2.8 1.2L12 16l-1.2-2.8L8 12l2.8-1.2Z" />
  </svg>
)

export const ShieldCheckIcon = () => (
  <svg {...common}>
    <path d="M12 3l7 3v5.5c0 4.4-2.9 7.7-7 9-4.1-1.3-7-4.6-7-9V6l7-3Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
)

export const SearchIcon = () => (
  <svg {...common}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
)

export const AlertIcon = () => (
  <svg {...common}>
    <path d="M12 3 2 20h20L12 3Z" />
    <path d="M12 10v4M12 17.5v.1" />
  </svg>
)

export const InboxIcon = () => (
  <svg {...common}>
    <path d="M4 12h4l1.5 3h5L16 12h4" />
    <path d="M5 12 6.5 5h11L19 12v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-6Z" />
  </svg>
)

export const ChevronDownIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="m6 9 6 6 6-6" />
  </svg>
)

export const LinkedInIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none">
    <path d="M4.98 3.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5ZM3 9.5h4v11H3v-11Zm6.5 0h3.8v1.5h.06c.53-1 1.83-2.06 3.77-2.06 4.03 0 4.77 2.65 4.77 6.1v5.46h-4v-4.84c0-1.16-.02-2.64-1.6-2.64-1.62 0-1.87 1.26-1.87 2.56v4.92h-4v-11Z" />
  </svg>
)

export const BuildingIcon = () => (
  <svg {...common}>
    <rect x="4" y="3" width="16" height="18" rx="1" />
    <path d="M8 7h1M8 11h1M8 15h1M15 7h1M15 11h1M15 15h1M10 21v-3h4v3" />
  </svg>
)
