// NOTE: We do not actually use Tailwind but having this file allows
// Tailwind-supporting IDEs to autocomplete classnames, most of which we follow by convention

// NOTE: Currently this has to be manually synced wit ./frontend/styles/vars.scss
module.exports = {
    content: ['./frontend/**/*.{js,jsx,ts,tsx}'],
    theme: {
        colors: {
            'primary-highlight': '#e8edff',
            'primary-light': '#345cff',
            primary: '#1d4aff',
            'primary-dark': '#1330a6',
            'danger-highlight': '#fbebe6',
            'danger-light': '#df4b20',
            danger: '#db3707',
            'danger-dark': '#992705',
            'warning-highlight': '#fef6e6',
            'warning-light': '#f8b633',
            warning: '#f7a501',
            'warning-dark': '#a06b01',
            'success-highlight': '#ebf3e5',
            'success-light': '#5f9d32',
            success: '#388600',
            'success-dark': '#245700',
            'primary-alt-highlight': '#ebecf0',
            'primary-alt': '#35416b',
            'primary-alt-dark': '#222a46',
            default: '#2d2d2d',
            'default-dark': '#050505',
            muted: '#5f5f5f',
            'muted-dark': '#403939',
            'muted-alt': '#747ea1',
            'muted-alt-dark': '#515871',
            white: '#fff',
            light: 'rgba(255, 255, 255, 0.878)',
            border: 'rgba(0, 0, 0, 0.15)',
            'border-light': 'rgba(0, 0, 0, 0.08)',
            'border-dark': 'rgba(0, 0, 0, 0.24)',
            'border-active': 'rgba(0, 0, 0, 0.36)',
        },
        extend: {
            screens: {
                sm: '576px',
                md: '768px',
                lg: '992px',
                xl: '1200px',
                xxl: '1600px',
            },
        },
    },
    plugins: [],
    // Comment in plugins that we have managed to replicate in our utilities.scss
    corePlugins: [
        // 'accentColor', // The accent-color utilities like accent-green-700
        // 'accessibility', // The sr-only and not-sr-only utilities
        'alignContent', // The align-content utilities like content-end
        'alignItems', // The align-items utilities like items-center
        // 'alignSelf', // The align-self utilities like self-end
        // 'animation', // The animation utilities like animate-ping
        // 'appearance', // The appearance utilities like appearance-none
        // 'aspectRatio', // The aspect-ratio utilities like aspect-square
        // 'backdropBlur', // The backdrop-blur utilities like backdrop-blur-md
        // 'backdropBrightness', // The backdrop-brightness utilities like backdrop-brightness-100
        // 'backdropContrast', // The backdrop-contrast utilities like backdrop-contrast-100
        // 'backdropFilter', // The backdrop-filter utilities like backdrop-filter
        // 'backdropGrayscale', // The backdrop-grayscale utilities like backdrop-grayscale-0
        // 'backdropHueRotate', // The backdrop-hue-rotate utilities like backdrop-hue-rotate-30
        // 'backdropInvert', // The backdrop-invert utilities like backdrop-invert-0
        // 'backdropOpacity', // The backdrop-opacity utilities like backdrop-opacity-50
        // 'backdropSaturate', // The backdrop-saturate utilities like backdrop-saturate-100
        // 'backdropSepia', // The backdrop-sepia utilities like backdrop-sepia-0
        // 'backgroundAttachment', // The background-attachment utilities like bg-local
        // 'backgroundBlendMode', // The background-blend-mode utilities like bg-blend-color-burn
        // 'backgroundClip', // The background-clip utilities like bg-clip-padding
        // 'backgroundColor', // The background-color utilities like bg-green-700
        // 'backgroundImage', // The background-image utilities like bg-gradient-to-br
        // 'backgroundOpacity', // The background-color opacity utilities like bg-opacity-25
        // 'backgroundOrigin', // The background-origin utilities like bg-origin-padding
        // 'backgroundPosition', // The background-position utilities like bg-left-top
        // 'backgroundRepeat', // The background-repeat utilities like bg-repeat-x
        // 'backgroundSize', // The background-size utilities like bg-cover
        // 'blur', // The blur utilities like blur-md
        // 'borderCollapse', // The border-collapse utilities like border-collapse
        'borderColor', // The border-color utilities like border-t-green-700
        // 'borderOpacity', // The border-color opacity utilities like border-opacity-25
        'borderRadius', // The border-radius utilities like rounded-l-lg
        // 'borderSpacing', // The border-spacing utilities like border-spacing-x-28
        'borderStyle', // The border-style utilities like border-dotted
        'borderWidth', // The border-width utilities like border-t-4
        // 'boxDecorationBreak', // The box-decoration-break utilities like decoration-clone
        // 'boxShadow', // The box-shadow utilities like shadow-lg
        // 'boxShadowColor', // The box-shadow-color utilities like shadow-green-700
        // 'boxSizing', // The box-sizing utilities like box-border
        // 'breakAfter', // The break-after utilities like break-after-avoid-page
        // 'breakBefore', // The break-before utilities like break-before-avoid-page
        // 'breakInside', // The break-inside utilities like break-inside-avoid
        // 'brightness', // The brightness utilities like brightness-100
        // 'caretColor', // The caret-color utilities like caret-green-700
        // 'clear', // The clear utilities like clear-right
        // 'columns', // The columns utilities like columns-auto
        // 'container', // The container component
        // 'content', // The content utilities like content-none
        // 'contrast', // The contrast utilities like contrast-100
        // 'cursor', // The cursor utilities like cursor-grab
        // 'display', // The display utilities like table-column-group
        // 'divideColor', // The between elements border-color utilities like divide-slate-500
        // 'divideOpacity', // The divide-opacity utilities like divide-opacity-50
        // 'divideStyle', // The divide-style utilities like divide-dotted
        // 'divideWidth', // The between elements border-width utilities like divide-x-2
        // 'dropShadow', // The drop-shadow utilities like drop-shadow-lg
        // 'fill', // The fill utilities like fill-green-700
        // 'filter', // The filter utilities like filter
        'flex', // The flex utilities like flex-auto
        // 'flexBasis', // The flex-basis utilities like basis-px
        'flexDirection', // The flex-direction utilities like flex-row-reverse
        'flexGrow', // The flex-grow utilities like flex-grow
        'flexShrink', // The flex-shrink utilities like flex-shrink
        'flexWrap', // The flex-wrap utilities like flex-wrap-reverse
        'float', // The float utilities like float-left
        'fontFamily', // The font-family utilities like font-serif
        'fontSize', // The font-size utilities like text-3xl
        // 'fontSmoothing', // The font-smoothing utilities like antialiased
        'fontStyle', // The font-style utilities like italic
        // 'fontVariantNumeric', // The font-variant-numeric utilities like oldstyle-nums
        'fontWeight', // The font-weight utilities like font-medium
        'gap', // The gap utilities like gap-x-28
        // 'gradientColorStops', // The gradient-color-stops utilities like via-green-700
        // 'grayscale', // The grayscale utilities like grayscale-0
        // 'gridAutoColumns', // The grid-auto-columns utilities like auto-cols-min
        // 'gridAutoFlow', // The grid-auto-flow utilities like grid-flow-dense
        // 'gridAutoRows', // The grid-auto-rows utilities like auto-rows-min
        // 'gridColumn', // The grid-column utilities like col-span-6
        // 'gridColumnEnd', // The grid-column-end utilities like col-end-7
        // 'gridColumnStart', // The grid-column-start utilities like col-start-7
        // 'gridRow', // The grid-row utilities like row-span-3
        // 'gridRowEnd', // The grid-row-end utilities like row-end-4
        // 'gridRowStart', // The grid-row-start utilities like row-start-4
        // 'gridTemplateColumns', // The grid-template-columns utilities like grid-cols-7
        // 'gridTemplateRows', // The grid-template-rows utilities like grid-rows-4
        'height', // The height utilities like h-72
        // 'hueRotate', // The hue-rotate utilities like hue-rotate-30
        // 'inset', // The inset utilities like top-44
        // 'invert', // The invert utilities like invert-0
        // 'isolation', // The isolation utilities like isolate
        'justifyContent', // The justify-content utilities like justify-center
        // 'justifyItems', // The justify-items utilities like justify-items-end
        // 'justifySelf', // The justify-self utilities like justify-self-end
        // 'letterSpacing', // The letter-spacing utilities like tracking-normal
        // 'lineHeight', // The line-height utilities like leading-9
        // 'listStylePosition', // The list-style-position utilities like list-inside
        // 'listStyleType', // The list-style-type utilities like list-disc
        'margin', // The margin utilities like mt-28
        'maxHeight', // The max-height utilities like max-h-36
        'maxWidth', // The max-width utilities like max-w-6xl
        'minHeight', // The min-height utilities like min-h-screen
        'minWidth', // The min-width utilities like min-w-min
        // 'mixBlendMode', // The mix-blend-mode utilities like mix-blend-hard-light
        // 'objectFit', // The object-fit utilities like object-fill
        // 'objectPosition', // The object-position utilities like object-left-top
        'opacity', // The opacity utilities like opacity-50
        // 'order', // The order utilities like order-8
        // 'outlineColor', // The outline-color utilities like outline-green-700
        // 'outlineOffset', // The outline-offset utilities like outline-offset-2
        // 'outlineStyle', // The outline-style utilities like outline-dashed
        // 'outlineWidth', // The outline-width utilities like outline-2
        // 'overflow', // The overflow utilities like overflow-x-hidden
        // 'overscrollBehavior', // The overscroll-behavior utilities like overscroll-y-contain
        'padding', // The padding utilities like pt-28
        // 'placeContent', // The place-content utilities like place-content-between
        // 'placeItems', // The place-items utilities like place-items-end
        // 'placeSelf', // The place-self utilities like place-self-end
        // 'placeholderColor', // The placeholder color utilities like placeholder-red-600
        // 'placeholderOpacity', // The placeholder color opacity utilities like placeholder-opacity-25
        'pointerEvents', // The pointer-events utilities like pointer-events-none
        // 'position', // The position utilities like absolute
        // 'preflight', // Tailwind's base/reset styles
        // 'resize', // The resize utilities like resize-y
        // 'ringColor', // The ring-color utilities like ring-green-700
        // 'ringOffsetColor', // The ring-offset-color utilities like ring-offset-green-700
        // 'ringOffsetWidth', // The ring-offset-width utilities like ring-offset-2
        // 'ringOpacity', // The ring-opacity utilities like ring-opacity-50
        // 'ringWidth', // The ring-width utilities like ring-4
        // 'rotate', // The rotate utilities like rotate-6
        // 'saturate', // The saturate utilities like saturate-100
        // 'scale', // The scale utilities like scale-x-95
        // 'scrollBehavior', // The scroll-behavior utilities like scroll-auto
        // 'scrollMargin', // The scroll-margin utilities like scroll-mt-28
        // 'scrollPadding', // The scroll-padding utilities like scroll-pt-28
        // 'scrollSnapAlign', // The scroll-snap-align utilities like snap-end
        // 'scrollSnapStop', // The scroll-snap-stop utilities like snap-normal
        // 'scrollSnapType', // The scroll-snap-type utilities like snap-y
        // 'sepia', // The sepia utilities like sepia-0
        // 'skew', // The skew utilities like skew-x-12
        // 'space', // The "space-between" utilities like space-x-4
        // 'stroke', // The stroke utilities like stroke-green-700
        // 'strokeWidth', // The stroke-width utilities like stroke-1
        // 'tableLayout', // The table-layout utilities like table-auto
        'textAlign', // The text-align utilities like text-right
        'textColor', // The text-color utilities like text-green-700
        // 'textDecoration', // The text-decoration utilities like overline
        // 'textDecorationColor', // The text-decoration-color utilities like decoration-green-700
        // 'textDecorationStyle', // The text-decoration-style utilities like decoration-dotted
        // 'textDecorationThickness', // The text-decoration-thickness utilities like decoration-4
        // 'textIndent', // The text-indent utilities like indent-28
        // 'textOpacity', // The text-opacity utilities like text-opacity-50
        // 'textOverflow', // The text-overflow utilities like overflow-ellipsis
        // 'textTransform', // The text-transform utilities like lowercase
        // 'textUnderlineOffset', // The text-underline-offset utilities like underline-offset-2
        // 'touchAction', // The touch-action utilities like touch-pan-right
        // 'transform', // The transform utility (for enabling transform features)
        // 'transformOrigin', // The transform-origin utilities like origin-bottom-right
        // 'transitionDelay', // The transition-delay utilities like delay-200
        // 'transitionDuration', // The transition-duration utilities like duration-200
        // 'transitionProperty', // The transition-property utilities like transition-colors
        // 'transitionTimingFunction', // The transition-timing-function utilities like ease-in
        // 'translate', // The translate utilities like translate-x-full
        // 'userSelect', // The user-select utilities like select-text
        // 'verticalAlign', // The vertical-align utilities like align-bottom
        // 'visibility', // The visibility utilities like visible
        'whitespace', // The whitespace utilities like whitespace-pre
        'width', // The width utilities like w-1.5
        // 'willChange', // The will-change utilities like will-change-scroll
        // 'wordBreak', // The word-break utilities like break-words
        // 'zIndex', // The z-index utilities like z-30
    ],
}
