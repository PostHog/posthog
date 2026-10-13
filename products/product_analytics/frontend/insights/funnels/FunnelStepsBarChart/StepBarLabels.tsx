export function StepBarLabels(): JSX.Element {
    return (
        <div className="StepBarLabels">
            {Array(6)
                .fill(null)
                .map((_, i) => (
                    <div key={i} className="StepBarLabels__segment">
                        <div className="StepBarLabels__label">{i * 20}%</div>
                    </div>
                ))}
        </div>
    )
}
