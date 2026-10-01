import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function Icon({ children, ...props }: IconProps): React.JSX.Element {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

export const CheckIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Icon>
)

export const AlertIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M12 9v4M12 17h.01" />
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  </Icon>
)

export const PlusIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)

export const CloseIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Icon>
)

export const ChevronLeftIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="m15 18-6-6 6-6" />
  </Icon>
)

export const ChevronRightIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="m9 18 6-6-6-6" />
  </Icon>
)

export const FolderIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  </Icon>
)

export const TrashIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
  </Icon>
)

export const PencilIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
  </Icon>
)

export const FileIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
    <path d="M14 3v6h6" />
  </Icon>
)

export const SearchIcon = (p: IconProps): React.JSX.Element => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Icon>
)

/** The app's mark: a plain two-stud brick. */
export const BrickIcon = (p: IconProps): React.JSX.Element => (
  <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true" {...p}>
    <rect x="9" y="5" width="6" height="5" rx="1.5" fill="currentColor" opacity="0.85" />
    <rect x="18" y="5" width="6" height="5" rx="1.5" fill="currentColor" opacity="0.85" />
    <rect x="4" y="9" width="24" height="17" rx="3" fill="currentColor" />
  </svg>
)
